# Knowledge Brain / Memory / Research Evolution — Detailed Task-Scoped Governance

Moved out of CLAUDE.md during **M4.6 — CLAUDE Context Normalization**. Registered as `id: KNOWLEDGE_MEMORY_RESEARCH`, `load_policy: TASK_SCOPED`. Sections preserved verbatim; only residency changed.

Covers: the 5-tier Memory system, Obsidian vault mechanics, research ingestion/distillation/applicability, confidence calibration, and the continuous-capability-evolution loops.

---

<!-- S050: moved verbatim from CLAUDE.md original lines 2155-2197 (M4.6 CLAUDE Context Normalization) -->
## Research Front Door: `dv-harness research` (2026-09-04)

A research-capability path exists (Stage 1 of the Research-Capability Evolution master prompt:
install the machinery, do not operate it). Nothing in this file mentioned it, so an agent reading
only CLAUDE.md had no way to know the entry point, the route, or the stop rule. The three assets
are `.claude/skills/research-ingestion/SKILL.md`, `.claude/agents/research-architect.md`, and
`dv_harness/capability_evolution.py`.

**The entry point is `dv-harness research`, not `/research`.** `.claude/commands/` does not exist
in this repo and never has, so the master prompt's own fallback applies ("implement equivalent
behavior using the repository's native mechanism"). Forms: `dv-harness research <doc>...`, plus
`--compare` / `--impact` / `--deep` (at most one; two is a refusal, not a silent precedence rule)
and `--focus regression|pss|debug|planning`. A focus narrows emphasis and never changes the route.
`--request "<free text>"` classifies a natural-language request through the same function an
unassisted request goes through.

**The route is fixed and it STOPS:** research-ingestion -> prior-evidence lookup (only when the
intent is COMPARE/DEEP/MULTI_DOCUMENT, or more than one document was supplied) -> research-architect
-> Human Approval Gate. The gate is the EXISTING `ControlPlane.approve()`, keyed on
`capability_evolution.HUMAN_APPROVAL_STAGE` (`RESEARCH_CAPABILITY_EVOLUTION`) -- not a new approval
mechanism. Research is not implementation: no capability-evolution change reaches production code
without `dv-harness approve RESEARCH_CAPABILITY_EVOLUTION --note ... --reviewer-id ...` first. That
stage id is admitted by the `approve` verb ALONE; `set-stage`/`redirect`/`correct`/`cosign` still
take real graph stages only, since those drive the engine loop and research owns no graph node.

**No new router, and non-interference is structural rather than careful.** The classifier lives in
`dv_harness/router.py` beside `resolve()` and shares its one `DEFAULT_ROUTES` table (which gained
exactly one pair, `research-route` -> `research-architect`). `RouteResolver.resolve()` -- the
function on `engine.py`'s real `run_stage()` path -- is untouched and is not a caller of any of it;
research routing is a separate `resolve_intent()` entry point. The classifier also reads only
`research_intent` and `protocol_hint`, never `modified_files`/`failing_test_name`/
`subsystem_boundary`, so a git-modified file named `paper.pdf` cannot hijack a DV debug run. A
request qualifies only on an ACTION+SUBJECT pair, and ambiguity resolves to NOT research.

**Honest limits.** No graph node declares `research-route`, so `.claude/agents/ROSTER.md` still
correctly records research-architect as `NOT_DISPATCHED` -- this is REACHED (a real CLI/agent
caller exists), not WIRED (no engine stage invokes it). Nothing here has been run against a real
external paper, and nothing research-origin may reach Organizational Memory on one session's
evidence. Proven by `dv_harness_tests/test_research_intent_routing.py` (84 tests), including the
master prompt's canonical natural-language request routing with no agent named, and 21 evidence
strings copied out of `test_protocol_router.py` answering bit-for-bit identically before and after.



<!-- S051: moved verbatim from CLAUDE.md original lines 2198-2228 (M4.6 CLAUDE Context Normalization) -->
## Research Stage Boundaries (2026-09-04)

The research capability above is now permanent and installed: the
`research-ingestion` skill turns ONE external document into ONE
provenance-carrying `ResearchEvidenceCard`, and the `research-architect` agent
compares cards and proposes a `CapabilityEvolutionCandidate`. Both are proven
operational by the master prompt's own 8 Stage-1 acceptance tests (A–H), listed
with their test names in `.work/gap-close-capability-evolution-acceptance-tests-report.md`.

**Installed is not running.** Two boundaries, and neither is a follow-on the
harness takes by itself:

- **Stage 2 — analyzing real external documents** (producing cards, the
  research-to-harness matrix, cross-document synthesis, gap analysis) starts
  only when a human asks for it, e.g. `dv-harness research <document>`. It never
  begins as the tail of a Stage-1 or Stage-0 task.
- **Stage 3 — implementing an approved capability change** requires a separate,
  explicit human decision recorded through the existing gate:
  `dv-harness approve --stage RESEARCH_CAPABILITY_EVOLUTION --note ...
  --reviewer-id ... --reviewer-confidence ...`. A strong card, a confident
  synthesis, or a HIGH-confidence candidate is never that approval, and reaching
  `main`/`master` still goes through the gh/PR-Only Governance Policy above.

Detail lives where it can stay current, per the Methodology Consolidation Rule —
do not re-inline it here: `research/README.md` (the tree, the stage table, the
independent-reading rule), `research/current_harness_baseline.md` (the Stage-0
audit of what L5 already had, and what Stage 1 reused rather than rebuilt),
`.claude/skills/research-ingestion/SKILL.md`, `.claude/agents/research-architect.md`,
and `dv_harness/capability_evolution.py`.



<!-- S062: moved verbatim from CLAUDE.md original lines 3314-3435 (M4.6 CLAUDE Context Normalization) -->
## Confidence Calibration: a Tier's Track Record vs. What It Buys (2026-09-05)

VERIFICATION_INTELLIGENCE's completeness audit flagged a Confidence Calibration
Engine NEVER_BUILT, and a full-repo `grep -ril calibrat` on 2026-09-05 confirmed
it: every hit was `architecture_calibration_gate` (an ARCHITECTURE-snapshot delta
gate) or a test fixture naming it. Nothing anywhere asked whether a CONFIDENCE
TIER's real track record matches what this harness treats that tier as being
worth -- and the two halves of that question had both been real and in production
for days.

`inference.score_confidence()` PRODUCES a tier (HIGH/MEDIUM/LOW) and
`MemoryConsolidator.from_closed_finding()` mints the fourth, CONFIRMED. Those
tiers are then SPENT as if their reliability were known:
`inference.promote_if_high_confidence()` pushes a HIGH finding into the shared
cross-user Knowledge Center, `memory_router.ENGINEERING_ADMISSION_CONFIDENCE_LEVELS`
admits only HIGH/CONFIRMED to the Engineering tier, and
`qualified_conclusion.build_qualified_conclusion()` refuses to qualify a LOW
conclusion at all. Meanwhile `memory.py` was RECORDING what later happened to
each of those conclusions the whole time -- `MemoryGC.confirm()` (the single
authorized writer of `confirmation_count`: "an independent, later run re-derived
the SAME conclusion with fresh evidence"), `MemoryGC.retract()` ("found to be
wrong outright") and `MemoryGC.supersede()` ("a newer, CORRECTED record replaces
this one"). The evidence to check a tier against its own history was on disk and
nothing read it back.

`dv_harness/confidence_calibration.py` reads it back and does nothing else. It
never re-scores a conclusion, never runs a gate, never writes a record.

**No stated reliability is invented, because this harness declares none.** No
number anywhere says "HIGH means 90%" -- every tier's meaning is a PROCEDURAL bar
(how much corroboration; which gates cleared), and fabricating a success rate to
measure a project against would be exactly the unearned claim the Evidence Truth
Rule forbids. What IS checkable without inventing anything is the ORDERING this
harness already acts on (CONFIRMED > HIGH > MEDIUM > LOW): a history in which a
higher tier holds up materially LESS often than a lower one contradicts that
ordering using only the project's own records. Every pair is compared, not just
adjacent ones. A project that wants an absolute bar declares one itself
(`confidence_calibration.tier_reliability_floor`); every tier's floor is None by
default and carries the real reason why, the same honesty contract
`loop_budget.py` applies to its eleven budget dimensions and
`loop_contract.validate_contract()` enforces on a `LoopContract`.

**Nothing is derived twice.** The tier vocabulary is `inference.CONFIDENCE_LEVELS`
plus `memory_router.ENGINEERING_ADMISSION_CONFIDENCE_LEVELS`, held equal in BOTH
directions by `assert_tiers_cover_inference_levels()` at import -- an uncalibrated
tier would be silently absent from every report. The corpus is read through the
real `MemoryStore.find()`, deliberately the same index-driven view
`MemoryRetriever.search()` has, with `index_integrity()` reported alongside so an
under-counted corpus is visible rather than silently smaller. The gap list is
`inference.identify_gap()` and every suggested action is produced by the REAL
`inference.next_best_action()` through its `gap_action_catalog` parameter -- the
domain-neutral engine `capability_evolution.py` and `golden_flow_readiness.py`
already drive the same way, and the one section 10 forbids re-implementing. Both
thresholds are derived from one another rather than chosen independently:
`MIN_DETERMINATE_OUTCOMES_PER_TIER = 10` is the smallest N at which `1/N <= 0.1`,
so a rate below it moves by more than the band it is read to, and
`INVERSION_TOLERANCE` is that same band.

**ACTIVE-and-never-re-checked is not evidence, and that is the whole point.** Most
records in any real store sit ACTIVE with zero confirmations; counting them as
verified would manufacture a 100% reliability for every tier out of records
nothing ever re-tested. They are INDETERMINATE with a named reason, as are
DEPRECATED (retired, not refuted) and NEEDS_REVALIDATION (nobody re-checked yet).
Rejection is checked BEFORE confirmation, so a record confirmed once and later
retracted is a REJECTED outcome -- the retraction is the last word about whether
the claim held.

**This harness's own answer today is INSUFFICIENT_HISTORY, and it is reported as
such.** Measured against this project's real store: 92 records scanned, 46
carrying a tier, and exactly ONE determinate outcome in the entire history (one
CONFIRMED record with a real confirmation; zero retractions). No tier can be
calibrated from that, so the report says so and names, per tier, the real outcome
this project would have to start recording. `NOT_AVAILABLE` (no store, or no
record carries a tier) stays distinct from `INSUFFICIENT_HISTORY` (records and
tiers exist, outcomes do not) -- different operator problems with different
fixes.

**Reading is never a mutating act.** A project with no memory store is reported
NOT_AVAILABLE WITHOUT constructing a `MemoryStore`, whose constructor would
`mkdir` the tree and write an empty `index.json` -- asking whether a project is
calibrated must not create the store it asked about. No human-approval gate is
referenced, let alone weakened: `ControlPlane.approve()`, `policy.can_signoff()`,
`assert_human_approval()`, `HumanApprovalRequiredError`,
`ProductionWriteNotAuthorizedError` and the PR-only main/master governance are
untouched and uncalled from this module, asserted against its own source and AST
by tests. Exit 2 means "not calibrated" -- a reporting signal, never an approval
signal in either direction.

Front door: `python -m dv_harness.confidence_calibration tiers|report|show`
(`execute_verb()`, the same shared convention `loop_contract`/`loop_budget`/
`loop_telemetry` follow). Proven by
`dv_harness_tests/test_confidence_calibration.py` (35 tests) against records
written by the REAL `MemoryStore.add()` / `MemoryGC.confirm()` / `retract()` /
`supersede()` / `deprecate()` / `flag_stale()`, never by hand-writing a record
file with the fields this module reads. The negative controls are what give it
detection power: nine determinate outcomes is still INSUFFICIENT_HISTORY and ten
is not, a sub-tolerance 80%-under-90% difference is NOT an inversion while one
more record's separation is, ten DEPRECATED records do NOT make a tier
calibratable at 0%, a one-outcome tier can never drag a well-evidenced one into a
finding, and the same machinery reports CALIBRATED over a store whose ordering
genuinely holds. Nothing in it runs a build, a regression or an LSF submission.

**One pre-existing defect was fixed to make this testable**:
`MemoryStore._save_index()` used a bare `os.replace()`, which on Windows raises
PermissionError (WinError 5) whenever a reader has `index.json` open at the
instant of the rename -- and that index really is read concurrently by every
`search()`/`find()`/`index_integrity()`. Writing ~200 records in a row surfaced
it on roughly one run in three. It now goes through the EXISTING
`storage._atomic_replace()` retry (the same one `blackboard.py` already uses),
not a second definition of "replace this file safely".

**Disclosed residual**: this is REACHED, not WIRED. There is no `dv-harness` CLI
verb (`cli.py` was being modified by concurrent work in the same session and
adding a verb there would have collided), no `run_stage()`/`advance()` call site
invokes it, no graph node declares it, and it is not on the dashboard. It also
calibrates the MEMORY-RECORD tier only: a `QualifiedConclusion`'s
`inference_confidence` reaches the Blackboard `qualified_conclusion` topic rather
than a MemoryStore record, and that topic keeps no history of what later happened
to the conclusion, so conclusions that never became a memory record are outside
the corpus. Closing that would need an outcome recorded against the conclusion
itself, which nothing writes today.


<!-- S084: moved verbatim from CLAUDE.md original lines 5229-5286 (M4.6 CLAUDE Context Normalization) -->
## VIP Learning Gate: One Pre-Generation Checkpoint (2026-09-06)

Four real, independently-built mechanisms each already answered their own question and each was
already wired into its own generation path: `vip_api_card.py` (PROVEN/BLOCKED/UNPROVABLE/
NOT_AVAILABLE over generated VIP API citations), `phy_boundary.py` (a real bind-location decision
from a real RTL port table), `connectivity.enforce_bind_tier_policy()` (T1..T4 bind-confidence
gate), and `env_manifest.py`'s `vip_config` layer (a real `$DESIGNWARE_HOME`/config-dump-derived
status). What did not exist anywhere was ONE consolidated checkpoint an agent could run before
generation and get back a single PASS/BLOCKED verdict naming which of the four is the reason -- a
repo-wide grep for `vip_learning_gate`/`learning_gate`/`pre_generation_gate` matched nothing
executable.

`dv_harness/vip_learning_gate.py` is that checkpoint, and it reuses rather than reimplements every
one of the four: `vip_api_card.validate_vip_api_usage()`, `phy_boundary.
assert_bind_location_allowed()`, `connectivity.enforce_bind_tier_policy()` and `env_manifest.
load_env_manifest()`'s own `vip_config.status` are each called and their real status is reported
verbatim, never re-derived. Per `vip_api_card.py`'s own documented statuses, a BLOCKED finding
blocks this gate while an UNPROVABLE finding is carried forward as a non-blocking WARNING (section
187's UNKNOWN is not a pass, but this gate's own task does not escalate it to a block either).
`phy_boundary.assert_bind_location_allowed()` and `connectivity.enforce_bind_tier_policy()` are
called for their real raise-or-not behaviour (a not-EXTRACTED/not-bindable boundary; a T4 entry or
a T3 entry lacking a real `question_queue.HUMAN_DECISION_SOURCE` confirmation), and
`env_manifest`'s `vip_config.status` is read for `NOT_AVAILABLE` verbatim.

**Absence is never a block, and it is never a fabricated pass either.** A sub-check with nothing
real to evaluate reports `NOT_APPLICABLE` (the caller declared nothing in scope -- no PHY boundary,
no bind entries, no VIP source/index pair -- a legitimate answer for an IP-level DUT with no PHY
sub-block or a run that binds nothing yet) or `NOT_AVAILABLE` (something was supplied but its real
producer could not decide, or `env.manifest.json` -- always expected -- was not supplied at all).
The composite is `BLOCKED` iff at least one sub-check is `BLOCKING`, naming exactly which; it is
`NOT_AVAILABLE` only when every sub-check is `NOT_APPLICABLE`/`NOT_AVAILABLE` (nothing at all could
be evaluated); otherwise `PASS`, carrying any `WARNING` forward rather than hiding it.

Front door: `python -m dv_harness.vip_learning_gate --vip-source ... --vip-index ... [--phy-boundary
<doc>] [--bind-entries <file>] [--env-manifest <doc>] [--json]` (`execute_verb()`, the same shared
convention `vip_api_card.py`/`golden_scenario.py` use); exit 0 PASS, 1 BLOCKED, 2 NOT_AVAILABLE.

**Deliberately bounded, and stated rather than implied closed.** (1) It decides and authorizes
nothing beyond reporting: no build, job, approval, memory write or stage gate; `ControlPlane.
approve()`, `policy.can_signoff()` and the human-approval machinery are untouched and unreferenced.
(2) It does not re-implement any of the four sub-checks' own judgment -- a BLOCKED vip_api_card
finding is BLOCKED for that module's own reasons, never a reason invented here. (3) There is no
`dv-harness` CLI subcommand: `cli.py`'s argparse tree plus concurrent edits from other parallel
gap-closure work in this same session made wiring one in cleanly awkward, per this project's own
allowance to skip CLI wiring and expose only `python -m dv_harness.<module>` when that is the case.

Proven by `dv_harness_tests/test_vip_learning_gate.py` (38 tests): each of the four sub-checks is
driven CLEAN over a real clean input (a small real synthetic VIP source indexed by the real
`vip_symbol_index.build_symbol_index()`, this repo's own real generated `phy_boundary.json`/
`phy_boundary_serial.json` example artifacts, real T1/T2/T3/T4 bind entries, a real generated
`env.manifest.json`), then every BLOCKING/WARNING/NOT_AVAILABLE/NOT_APPLICABLE path is driven by a
single real defect or omission (the same `apply_preset` -> `apply_prezet` mutation
`test_vip_api_card.py` uses, an open-inheritance-chain UNPROVABLE fixture, a real UNDECIDABLE
`phy_boundary.extract_phy_boundary()` call, an unconfirmed vs. confirmed T3 entry pair, and both
real `env.manifest.json` `vip_config` states). Composite tests assert that a single offending
sub-check is named alone and that multiple blocking sub-checks are all named together, and five
real CLI subprocess invocations assert exit codes 0/1/2.


<!-- S091: moved verbatim from CLAUDE.md original lines 5683-5732 (M4.6 CLAUDE Context Normalization) -->
## DE Command-Style Learning: CommandStyleIR + DECommandRegistryIR (2026-09-06)

Nothing in this repo learned a DE-provided command.txt's own real FORMATTING convention or built
a per-command REGISTRY view with a branch-ownership guess before generating from it -- a repo-wide
grep confirmed reference_pattern_audit.py's real SYS-7 layer (extract_command_statements,
classify_wait, analyze_command_file) already classifies every statement's kind/category and
role, but asks nothing about the file's own SEPARATOR/ARGUMENT/COMMENT/PHASE-MARKER/ORDERING style,
and produces no per-distinct-command view carrying a GLOBAL/DUT/FW/VIP branch-ownership guess.

dv_harness/de_command_style_learning.py is that second layer, and it REUSES rather than
re-derives statement parsing: it imports reference_pattern_audit.extract_command_statements() (a
pre-existing, independently-tested module) plus its CommandStatement/kind-category vocabulary and
its INTERRUPT_NAME_TOKENS/INIT_NAME_TOKENS/MEMORY_MODEL_NAME_TOKENS token sets, rather than
writing a second statement classifier that could disagree with the first.

CommandStyleIR is pattern-detected directly from a real file's own text -- never assumed --
covering separator_convention (semicolon-terminated one-per-line vs multi-statement/multi-line,
from the real ratio of single-semicolon lines), argument_format (paren/comma-separated calls, hex
literal style with/without underscore grouping), comment_format (line-trailing vs standalone,
block comments), phase_markers (a real PHASE:/STAGE:/STEP:/SECTION:-shaped token, never a
plain word like "stage1" that merely contains the substring), and ordering_rules (real
fork/join keywords, and comment-level ordering language). Every facet with no evidence reports
NOT_FOUND/NOT_AVAILABLE naming the real search performed, never a guessed convention.

DECommandRegistryIR groups statements into one DECommandEntry per distinct (kind, name)
command (an unclassifiable line is grouped only with another line carrying IDENTICAL raw text,
since it has no other real name), each carrying a best-effort semantic_operation, its
arguments, a branch_owner GUESS in GLOBAL/DUT/FW/VIP/UNKNOWN -- the four real layers
.claude/skills/CORE/branch-mapper/SKILL.md's "Initialization Task Hierarchy" names (block=
GLOBAL, branch_a*=DUT, branch_fw=FW, branch_b*=VIP) -- and a status in KNOWN/PARTIAL/
AMBIGUOUS/UNSUPPORTED/DEPRECATED/UNKNOWN. KNOWN requires a real cited textual feature (e.g. a
HOSTWRITE*/CPUWRITE* prefix, per reference_pattern_audit's own real HOST-vs-DUT naming
convention, or an INTERRUPT_NAME_TOKENS match on a wait condition); AMBIGUOUS/PARTIAL mark a
genuine guess; UNKNOWN is reserved for a line the underlying parser could not classify at all --
its command_name/raw_text is that line's literal source text, cited verbatim, never
paraphrased into invented semantics. A comment carrying a real deprecation token
(deprecated/obsolete/do not use/etc.) flags the whole command DEPRECATED, citing the exact
comment and matched token -- taking priority over the ordinary mixed-classification-across-
occurrences downgrade to AMBIGUOUS, since a real deprecation notice is stronger evidence than an
occurrence disagreement.

Proven by dv_harness_tests/test_de_command_style_learning.py (19 tests) against a small real
synthetic fixture built inline (never real project content, matching
test_reference_pattern_audit.py's own precedent), covering KNOWN host/DUT register writes,
DEPRECATED (a comment-flagged legacy write), a KNOWN FW interrupt wait merged with an AMBIGUOUS
plain wait into one mixed-classification entry, an UNSUPPORTED bare macro, and an UNKNOWN
unparseable line, plus dedicated CommandStyleIR tests including a phase-marker true-negative (a
plain word containing "stage" is not a marker) and true-positive, and an empty-file
NOT_AVAILABLE/NOT_FOUND-everywhere control.


<!-- S114: moved verbatim from CLAUDE.md original lines 7211-7299 (M4.6 CLAUDE Context Normalization) -->
## Design Knowledge Correlation: Cross-Source Conflict / Gap / Doc-vs-Impl (2026-09-06)

A generic cross-source correlation engine over IR-shaped "design knowledge" facts. Every existing
correlator in this repo answers a narrower question against one specific real producer's own shape:
`dut_evidence_correlation.py` joins ONE caller-declared item against `env_manifest.py`'s `dut_facts`
layers; `env_manifest.py`'s own `testplan_correspondence` is a fixed three-way join of ONE project's
testlist/vPlan/coverage-model triple; `source_authority.py` decides which of TWO already-identified
conflicting VALUES wins given a 9-level authority order, but never DISCOVERS a conflict on its own.
Nothing took an arbitrary NUMBER of arbitrarily-shaped knowledge sources and found where they agree,
disagree, or leave a gap. `dv_harness/design_knowledge_correlation.py` is that general engine.

**Per this batch's file-safety scope, it imports nothing from `dv_harness` itself.** A "source" is a
plain dict (`source_id`, `source_kind` -- free text, purely descriptive -- `role`, `facts`), and
`role` is one of `SPEC_DECLARATION` / `IMPLEMENTATION_EVIDENCE` / `OTHER`, deliberately **declared by
the caller** rather than guessed from `source_kind` text (guessing would be exactly the fabricated
semantics the Evidence Truth Rule forbids). A future caller sitting in front of a real producer would
build this shape from that producer's own real output -- one fact per `env_manifest.py` `dut_facts`
entry (role IMPLEMENTATION_EVIDENCE), one per a real `requirement_contract.py`-validated record's
`feature`/`expected_behavior` field (role SPEC_DECLARATION), one per a vPlan item (role OTHER) --
this module does not parse any of those itself, the same extraction-shaped boundary
`dut_evidence_correlation.py` and `doc_extraction_fanout.py` already draw around requirement prose.

**Three finding categories, plus one assembled artifact:**
- **CONFLICT** -- two or more sources assert different values for the same `fact_key`. The join is
  a literal exact-string `fact_key` match, never fuzzy (the same discipline
  `env_topology.testplan_correspondence` already states the reason for). Values are compared by a
  representation-tolerant, substance-strict comparator (`"HIGH"`==`"high"`, `100`==`100.0`,
  `True`=="true"`, but `100` vs `200` is a real conflict), clustered into equivalence classes; more
  than one class is a CONFLICT, reported with every distinct value and its citing source(s). **No
  arbitration**: this module never decides which side is right -- that is
  `source_authority.resolve_conflict()`'s job (a real, existing, narrower mechanism deliberately left
  untouched and not imported here), or a human's.
- **GAP** -- a fact the caller explicitly declared EXPECTED (`expected_facts`, each carrying a
  `reason`/`required_by` citation) that no supplied source covers at all. Without a declared
  expectation, "a fact no source covers" is undecidable (no enumerated universe of facts a design
  SHOULD have exists), the same reason `config_variant_coverage.py` requires a caller-declared
  dimension space -- `correlate()` with no `expected_facts` reports zero gaps, honestly, rather than
  fabricating an expectation.
- **DOCUMENTED_VS_IMPLEMENTED** -- a fact_key declared by a SPEC_DECLARATION-role source with no
  IMPLEMENTATION_EVIDENCE-role source ever asserting it (`..._SPEC_ONLY`), or the reverse
  (`..._IMPLEMENTATION_ONLY`). It is a PRESENCE check on `role`, not a values check: a fact both
  sides spoke to, whose values then disagree, is reported once, as a CONFLICT -- the two categories
  are kept disjoint so one real disagreement is never counted twice. OTHER-role-only coverage yields
  no doc-vs-impl finding either way, since this module cannot judge a documentation question about a
  fact neither canonical side spoke to.
- **Design Knowledge Graph** -- every source and fact assembled into one graph (`SOURCE` / `FACT`
  nodes, `ASSERTS` edges), with **per-node provenance**: each FACT node embeds its own full
  `provenance` list (which source, what value, what evidence_ref, what role) inline, so a reader does
  not have to walk the edge list to see who said what, plus a `consensus` field
  (`SINGLE_SOURCE`/`AGREEMENT`/`CONFLICT`) computed from the same clustering the CONFLICT detector
  uses.

Front door: `correlate(sources, expected_facts=None)` (the module's one entry point; raises
`DesignKnowledgeCorrelationError` -- a fail-closed, caller-usage error, never a silent skip -- on a
malformed source/fact/expected-fact), `build_knowledge_graph(sources)` (independently callable), and
`python -m dv_harness.design_knowledge_correlation --sources <file.json> [--expected-facts <file.json>]
[--json]` (exit 0 clean, 1 a real finding, 2 malformed input). No `dv-harness` CLI verb was added
(`cli.py` is out of this task's file-safety scope); a suggested verb entry is available for an
integrator to add.

**Deliberately bounded, and stated rather than implied closed.** (1) No arbitration, by design --
CONFLICT reports the disagreement and cites both sides' evidence; deciding which is right is a human
decision or `source_authority.resolve_conflict()`'s. (2) GAP detection is gated entirely on a
caller-declared `expected_facts` list; this module invents no expectation of its own. (3)
DOCUMENTED_VS_IMPLEMENTED is a role-presence check, not a semantic one -- a fact asserted only by
OTHER-role sources is never judged. (4) The join key (`fact_key`) is matched by exact string equality
only; no fuzzy/semantic matching, and no unit conversion (100 MHz vs 0.1 GHz reads as a genuine
conflict) -- normalizing heterogeneous naming/units across real producers is a separate,
extraction-shaped problem this module does not attempt. (5) It decides nothing beyond the three
finding categories and the graph: no build, no job, no approval, no stage gate, no memory write, and
no I/O beyond the optional CLI reading the two files the caller names. (6) It generates nothing --
no VIP API, no RTL content, no protocol behavior -- it only correlates facts a caller already
extracted.

Proven by `dv_harness_tests/test_design_knowledge_correlation.py` (27 tests) against small, synthetic
IR-shaped fixtures constructed directly in the test file (never another module's real output, since
the whole point is to prove the correlation logic itself): a clean fully-agreeing correlation reports
zero findings and correct per-node provenance; the value comparator is proven representation-tolerant
(case/whitespace/numeric-repr/bool-as-string) but substance-strict (a real 100-vs-200 disagreement is
still caught); CONFLICT is proven on a real two-way and a real three-way value split; GAP is proven
present only when declared-expected and absent, and absent when no expectation was declared or when
any source covers it; both DOCUMENTED_VS_IMPLEMENTED directions are proven, including the negative
control that both-sides-present-but-disagreeing is CONFLICT and never additionally a doc-vs-impl
finding, and that OTHER-role-only coverage yields neither; and nine negative controls drive malformed
input (empty/non-list sources, duplicate source_id, missing fact_key/value, invalid role, malformed
expected_facts) to a real `DesignKnowledgeCorrelationError` rather than a silent pass. The CLI is
driven as four real subprocesses (clean/conflict/malformed/expected-facts-gap), asserting real exit
codes and real JSON output.


<!-- S117: moved verbatim from CLAUDE.md original lines 7479-7579 (M4.6 CLAUDE Context Normalization) -->
## Design Knowledge Output Package: the Family's Exportable Bundle + Downstream-Consumer Contract (2026-09-06)

The design-knowledge family grew to six real modules -- `design_source_inventory.py` (where design
sources are, freshness, authority), `design_knowledge_correlation.py` (cross-source CONFLICT/GAP/
DOCUMENTED_VS_IMPLEMENTED), `design_intent.py` (intent.md/constraints.md distillation), `design_
architecture_ir.py` (RTL module/instance tree + FSM scan), `spec_intelligence.py` (spec-extraction
schema + re-derivation gate), `verification_intent_ir.py` (the semantic bridge to a generator) -- with
no single exportable package assembling their outputs together, and no documented statement of which
of those six outputs' fields a downstream generator (a vPlan writer, a scenario planner, a checker/
coverage generator) may simply TRUST versus which it must independently RE-VERIFY. A generator reading
`design_knowledge_correlation`'s `conflicts` list and silently picking a winning value itself, or
reading `verification_intent_ir`'s `objective` text as a verified fact instead of an interpretation,
would reproduce exactly the fabrication the Evidence Truth Rule exists to catch, and nothing said so in
one place. `grep -rn "downstream_consumer_contract" --include=*.py .` before this module matched
nothing.

`dv_harness/design_knowledge_output_package.py`'s `collect_design_knowledge_package(root, out_dir,
**six_slots, require_complete=False)` closes both gaps at once, reusing rather than reimplementing:

- **No second implementation of any family member.** Each of the six slots calls that module's own
  real entry point directly (`design_source_inventory.build_source_registry()`, `design_knowledge_
  correlation.correlate()`, `design_intent.validate_intent`/`validate_constraints`/`render_intent_
  markdown`/`render_constraints_markdown`, `design_architecture_ir.build_architecture_ir()`, `spec_
  intelligence.analyze_spec_extraction()`, `verification_intent_ir.build_verification_intent_ir_set()`)
  -- see `_LIVE_DISPATCH`/`_resolve_design_intent()`. `design_intent` is the one slot shaped
  differently: its module produces up to TWO independent documents (intent/constraints), so this module
  bundles up to four sub-artifacts (`design_intent:intent_doc`/`:intent_markdown`/`:constraints_doc`/
  `:constraints_markdown`) rather than forcing one false present/absent boolean over two genuinely
  independent documents. A partial success (intent validates, constraints does not) reports BOTH the
  real intent output and the real constraints error -- neither masks the other.
- **No second bundler.** The packaging mechanics are `signoff_export.compute_bundle_hash()` and
  `signoff_export._artifact_content_digest()`, called directly -- the identical reuse `system_signoff_
  package.py` already established for the system-scope sibling of this same bundle. Every manifest
  entry carries the identical four-key shape (`artifact`/`present`/`bundled_path`/`content_sha256`)
  those two already produce.
- **LIVE vs CALLER-SUPPLIED per slot**, mirroring `system_signoff_package.py`'s `subsystems`/
  `subsystem_contracts` split at slot instead of list granularity: `{"live": {<kwargs>}}` calls the
  real producer itself (a real exception is caught and reported as the slot's error, never crashing the
  whole package -- the same per-artifact honesty `system_signoff_package.py`'s own `_assemble_one_
  subsystem()` already applies); `{"record": <precomputed output>}` accepts an already-real output a
  caller ran elsewhere, duck-typed exactly as `system_signoff_package.py`'s own `subsystem_contracts`
  parameter already is. `None` is `NOT_REQUESTED` -- kept distinct from a requested-but-failed slot for
  the identical reason `signoff_export.SIGNOFF_STATUS_NOT_RECORDED` is kept distinct from `NOT_STARTED`.
- **Worst-wins `package_kind`** (CLAUDE.md's composite-gate rule, applied at slot-assembly granularity,
  not at content-quality granularity): `PACKAGE_ASSEMBLY_COMPLETE` only when at least one slot was
  requested AND every requested slot came back present with no error; `PACKAGE_ASSEMBLY_PARTIAL`
  otherwise, one missing/errored requested slot dragging the WHOLE package down regardless of how many
  others are clean. Zero slots requested is `PARTIAL`, not `COMPLETE`. `package_kind` deliberately does
  NOT judge the design knowledge's own content -- a package can be `COMPLETE` while its bundled `design_
  knowledge_correlation.json` carries real CONFLICT findings, the same separation `signoff_export.
  collect_signoff_bundle()` already keeps between a bundle's own `status: OK` and the project's real
  SIGNOFF verdict. `require_complete=True` refuses and writes nothing at all (not even an empty
  `out_dir`) unless every requested slot landed clean -- the identical refusal contract `collect_
  signoff_bundle(require_signoff_pass=True)` and `collect_system_signoff_package(require_system_
  signoff_pass=True)` already keep.
- **The documented downstream-consumer contract.** `DOWNSTREAM_CONSUMER_CONTRACT` (module-level, one
  entry per family slot, each declaring non-empty `may_rely_on` / `must_reverify` lists) is not invented
  here -- every line traces to a real boundary statement already written in the owning module's own
  docstring: `design_knowledge_correlation.py`'s "no arbitration" boundary (the same ARBITRATION
  boundary `requirement_contract.py` keeps for its own conflict findings) -- a generator must never
  auto-pick a value out of a `CONFLICT` finding's groups; `verification_intent_ir.py`'s `evidence_
  provenance.AGENT_SELF_ATTESTED` self-attestation on every interpretive field, versus the verbatim-
  preserved real per-domain evidence where a real producer exists; `design_architecture_ir.py`'s
  best-effort FSM scan (never a verified model); `design_intent.py`'s citation-required transcription
  boundary (a citation proves a source was NAMED, not that the transcription is faithful to it);
  `spec_intelligence.py`'s evidence-provenance caveat; `design_source_inventory.py`'s freshness-is-as-
  of-`last_checked` framing. `assert_contract_covers_family()` runs at import, holding `FAMILY_SLOTS`
  and the contract's own key set equal in both directions -- the identical never-silently-drift
  discipline `signoff_export.assert_baseline_covers_section_238()` already keeps for its own fixed
  field list. The contract is bundled into every package as `downstream_consumer_contract.json`
  regardless of which slots were requested, since it documents the FAMILY, not one run's data.

**Deliberately bounded / disclosed residuals**: (1) `verification_intent_ir`'s `power_intent_report`
kwarg (a non-JSON-serializable object) is not wired into this module's live dispatch for that slot --
only `source_paths`/`sys_regmap_doc`/`upf_paths` are; a caller who has run `power_intent.analyze_power_
intent()` and wants it reflected builds the full IR set itself and supplies it as `{"record": [...]}`.
(2) No `STAGE_GATES` entry and no `dv-harness` CLI verb -- `cli.py`/`gates.py` are out of this task's
file-safety scope; the front door is `python -m dv_harness.design_knowledge_output_package collect
--root <dir> --out-dir <dir> --config <config.json> [--require-complete] [--json]`, the same disclosed
choice `system_signoff_package.py` and several other recent sibling modules already make.

Proven by `dv_harness_tests/test_design_knowledge_output_package.py` (19 tests): every LIVE slot is
driven by a REAL call into that family member's own real entry point -- `design_source_inventory`
hashing a real temp file, `design_knowledge_correlation` finding a real conflict between two real
sources, `design_intent` validating and rendering the project's own real worked-example fixture
(`examples/asset_processing/inputs/dut_intent.yaml`/`constraints.yaml`, the same fixture `test_asset_
processing_artifacts.py`'s own design_intent tests use), `design_architecture_ir` running the real
verible binary installed in this environment over a real synthetic `.sv` file, `spec_intelligence`
validating a real extraction document, `verification_intent_ir` building a real IR carrying the real
`AGENT_SELF_ATTESTED` self-attestation this module's own contract cites. `bundle_hash` is cross-checked
against an independent direct call into `signoff_export.compute_bundle_hash()`. Negative controls prove
a malformed `sources` list, a schema-invalid `intent_doc`/`constraints_doc`, an unresolvable `top_
module` override, and a request naming both `record` and `live` are all reported honestly (`present:
False`, a real error string, `package_kind: PACKAGE_ASSEMBLY_PARTIAL`) rather than fabricated as
present -- including a partial-success case proving one half of `design_intent`'s two documents can
land for real while the other's real failure is reported alongside it, neither masking the other. The
full family suite (`test_design_architecture_ir.py`, `test_design_knowledge_correlation.py`, `test_
design_source_inventory.py`, `test_spec_intelligence.py`, `test_verification_intent_ir.py`, `test_
signoff_export.py`, `test_system_signoff_package.py`, `test_asset_processing_artifacts.py`) plus this
module's own suite -- 311 tests total -- passes together, confirming no regression to any reused module.


<!-- S161: moved verbatim from CLAUDE.md original lines 9753-9768 (M4.6 CLAUDE Context Normalization) -->
## AMBA Functional Coverage IR: Connectivity/Memory-Map/Routing/Ordering Coverpoints, 7-Value Reachability, Meaningful Crosses Only (2026-09-06)

Nothing in this repo's existing, extensive AMBA family (`amba_fabric_discovery.py`, `amba_port_registry.py`, `amba_fabric_analysis.py`, `amba_transaction_ir.py`, `amba_route_transform_predictor.py`) turned their real discovery/analysis facts into a functional-coverage IR: a set of coverpoint bins driven by connectivity legality, memory-map ownership, routing/transform paths, and ordering scenarios, each carrying an honest reachability classification rather than a binary covered/uncovered flag. `dv_harness/amba_functional_coverage_ir.py` is that IR, and it is deliberately standalone: per this batch's file-safety scope it imports neither `connectivity.py` nor `amba_master_slave_constraint_ir.py` (a separate task in the same batch owns the latter) and no other new module from this batch -- connectivity-legal-edge facts, address-region facts, route facts and ordering facts are all accepted as generic, duck-typed dict lists, the same "accept an explicit caller-declared fact rather than invent one" discipline `ip_ownership_conflict.py`'s `legacy_bfm_declarations` and `existing_command_reuse_score.py`'s `existing_commands` already established for a fact their own real evidence store cannot supply on its own.

**A 7-value reachability classification, never collapsed to binary.** `classify_bin_reachability(fact)` derives one of `COVERED_OBSERVED` / `REACHABLE_NOT_YET_HIT` / `PARTIALLY_REACHABLE_CONDITIONAL` / `UNREACHABLE_NO_LEGAL_PATH` / `UNREACHABLE_STRUCTURALLY_EXCLUDED` / `REACHABILITY_CONTRADICTED` / `REACHABILITY_UNKNOWN_INSUFFICIENT_EVIDENCE` from real evidence fields on the caller's fact dict (`observed_hit`, `legal`, `structurally_excluded`, `conditional`, `contradicting_evidence`) -- the AMBA-specific instance of the same discipline `coverage_analysis.classify_coverage_hole()`'s four root causes and this same session's `pattern_coverage_contribution.classify_cross_coverage_meaningfulness()` already apply elsewhere: never let an absence of proof read as a confirmed negative, and never let two different kinds of "not covered" collapse into one word. A real observed hit always wins over every other field. A `structurally_excluded` fact asserted alongside an affirmatively-`legal` connectivity fact is DERIVED as `REACHABILITY_CONTRADICTED` even when the caller never flagged the disagreement explicitly -- a real, checked disagreement between two evidence sources, not a guessed one.

**Four coverpoint builders**, each a thin, duck-typed reduction of a category of real caller-supplied facts into coverpoint bins: `build_connectivity_coverpoints(legal_edges)` (one bin per master-slave/source-dest pair), `build_memory_map_coverpoints(address_regions)` (one bin per owner/region, optionally crossed with an accessing master), `build_routing_coverpoints(route_facts)` (one bin per source-dest route, optionally naming its hop sequence), `build_ordering_coverpoints(ordering_facts)` (one bin per named ordering scenario -- outstanding-transaction-depth buckets, out-of-order-completion scenarios -- optionally scoped to a real master/ID). None of the four derives connectivity legality, address-map ownership, routing behaviour, or ordering semantics itself; each accepts a real, caller-supplied fact per bin and classifies its reachability through the shared `classify_bin_reachability()`.

**"Meaningful crosses only" is reimplemented independently, not imported**, per this task's own explicit instruction: `classify_cross_coverage_meaningfulness()` in `amba_functional_coverage_ir.py` is a fresh implementation of the identical small idea `pattern_coverage_contribution.py`'s own function of the same name already solves for its domain -- both answer "are this cross's two axes already fully explained by their own single-axis coverage" from the same `{"bins_total","bins_hit"}` category-snapshot shape, independently, by design for this batch. `evaluate_cross()` wires this into bin-building: a cross whose two declared axes are BOTH already 100% `COVERED_OBSERVED` is reported `FULLY_EXPLAINED_BY_AXES` and SKIPPED -- zero per-combination cross bins are built at all, because the point of "meaningful crosses only" is to not even track a cross whose information the two single-axis bin sets already fully carry. A cross missing evidence for either axis is `UNKNOWN_AXIS_COVERAGE`, never silently read as either meaningful or fully explained.

`AMBAFunctionalCoverageIR.build(legal_edges=, address_regions=, route_facts=, ordering_facts=, cross_requests=)` assembles all four coverpoint categories plus zero or more cross evaluations (each cross request may name its two axes' snapshots directly, or reference one of this same call's own just-built categories via `axis_a_category`/`axis_b_category`, through the new `axis_snapshot_from_bins()` reducer -- never a stale, separately-passed axis set) into one `all_bins()`/`reachability_summary()`/`to_dict()`-capable IR. `dv-harness` was not touched (per this task's own file-safety scope); the ad hoc front door is `python -m dv_harness.amba_functional_coverage_ir build --facts <file.json> [--json]`.

**Deliberately bounded, and stated rather than implied closed.** (1) It decides nothing beyond classification and cross-selection: it writes nothing to any evidence store, mints no memory/blackboard/approval record, runs no build/regression/LSF submission, and there is deliberately no stage gate -- a gate that passed on a coverage IR nobody reviewed would be worse than none. (2) It never derives connectivity legality, address-map ownership, routing/transform behaviour, or ordering semantics itself -- every one of those is a real fact a caller's own pipeline (a real connectivity pass, a real address-map cross-check, `amba_route_transform_predictor.py`, a real ordering/ID-tracking analysis) must supply; this module only turns already-real facts into coverpoint bins and classifies them honestly. (3) It imports no other module from `dv_harness` at all, including no other new module built in this same batch, so it stays usable regardless of which concurrently-built sibling module (`amba_master_slave_constraint_ir.py` included) eventually lands.

Proven by `dv_harness_tests/test_amba_functional_coverage_ir.py` (47 tests): the classifier's 7-way disjoint outcomes including a dedicated test proving all seven values are independently reachable from real input shapes and the derived-contradiction case; each of the four coverpoint builders' positive paths plus identity/duplicate/malformed negative controls; the meaningful-crosses-only skip-vs-track behavior (including the category-derived axis-snapshot path, proven both to skip a fully-explained cross with zero bins and to build real bins for a genuinely meaningful one); the assembled IR's cross-request wiring and its negative controls (missing axis names, an unrecognized category); a full JSON round-trip proof; an empty-build control; and the real CLI driven both in-process and as a real subprocess. `python -m pytest dv_harness_tests/test_amba_functional_coverage_ir.py -q` -> `47 passed`.


<!-- S188: moved verbatim from CLAUDE.md original lines 10676-10777 (M4.6 CLAUDE Context Normalization) -->
## Multi-Hop Memory-Promotion Lineage Walker (2026-09-07)

Section-level answer to "how did this Organizational-tier conclusion actually get here, hop by
hop, all the way back to the evidence" -- a question CLAUDE.md's own Engineering Memory Policy
already implies ("Any current root cause must be revalidated with current evidence") but nothing
in this repo could actually answer end to end. Verified first, per house rule 4: `memory_router.
organizational_admission_gate()` already reads `source_engineering_memory_id` (the real, single
back-pointer memory_router.py's own promotion-provenance check re-reads at write time), and
`research_engineering_admission_reasons()` already reads `corroborating_memory_ids` -- but each
stops at depth 1, for its own single purpose (is the immediate source ACTIVE/gate-validated;
count distinct source documents). Neither ever walks a chain, and neither builds anything a human
or another tool could query.

`dv_harness/memory_lineage.py` is that walker: standalone, read-only, additive -- zero changes
to `memory.py`/`memory_router.py`/`memory_vault.py`/`engine.py`. Starting from an
Organizational-tier record (a caller-supplied record dict, or -- since `memory.
OrganizationalMemoryStore` has no local per-tier JSON file by design -- the local DV-Knowledge
Vault mirror `memory_router._maybe_write_vault_note()` already writes on every real promotion),
it recursively resolves `source_engineering_memory_id` and `corroborating_memory_ids` (cycle-
detected, depth-capped) via real local `MemoryStore.get()` calls for every job/engineering/
project/working-tier hop.

**Two honesty limits, disclosed on every node rather than papered over.** (1) `MemoryGC.
confirm()` OVERWRITES `last_confirmation_evidence` on every call -- there is no per-event
confirmation history anywhere in this schema, only a count -- so a record confirmed N times
carries only the MOST RECENT confirming evidence; the walker states this on every node rather
than fabricating a history. (2) The vault mirror's frontmatter does not carry
`source_engineering_memory_id` at all (only the note BODY's "Related Knowledge" section does, as
a bare `[[id]]` wikilink with no field name attached), and that same section can also carry
`memory_router._related_knowledge_with_links()`'s own RELATED-similarity wikilinks (always
suffixed `"(related, similarity N.NN)"`), which are never a derivation hop. The walker filters
those out by their real structural suffix and reports any remaining bare wikilink as an honestly
AMBIGUOUS lineage candidate (still resolved, just unable to name which of
`source_finding_id`/`source_engineering_memory_id` produced it) rather than guessing.

`source_finding_id` (a real field `MemoryConsolidator.from_closed_finding()` writes) is reported
as a cited EXTERNAL reference and never resolved as a memory_id -- it names a Blackboard
finding_id, and "Blackboard stores current verification truth" (Core Operating Rules), not a
durable memory-tier record. A terminal Engineering-tier node with no further resolvable
back-pointer surfaces its own inline job/simulation-level evidence fields (`evidence`,
`verification`, `git_sha`, `rtl_sha`, `tb_sha`, `test`, `result`) as the honestly-labelled
"original Job-tier evidence" when no separately-stored Job-tier `MemoryStore` record could be
reached from it (only a real `corroborating_memory_ids` link reaches one of those today -- no
production write path sets any other back-pointer from Engineering straight to a Job-tier
memory_id).

**Never mints state.** `build_lineage()`/`build_organizational_lineage()` never construct a
`MemoryStore` (which `mkdir()`s the whole tier tree) or call `config.load_config()` (which WRITES
a default `config.json`) on a project that has neither a local memory store nor a vault already
on disk -- mirroring `cross_project_mining.has_memory_store()`'s own established discipline,
proven directly by a real before/after file-listing snapshot. It never contacts the remote,
cross-user Knowledge Center: vault resolution goes only through `memory_vault.
get_active_provider()`'s local `FileSystemMarkdownAdapter` (optionally paired with a LOCAL
Obsidian REST probe), the identical path every existing `dv-harness memory search` call already
uses.

**It arbitrates nothing.** `memory_router.organizational_admission_gate()` remains the only real
gate deciding whether a record SHOULD have promoted; this module only reconstructs, honestly,
what lineage already exists -- a dangling reference is reported (`PARTIALLY_RESOLVED`, naming the
exact field and reason), never silently dropped, and an unresolvable root is `ROOT_UNAVAILABLE`,
never a fabricated empty chain. `collect_job_tier_evidence()` gives the walk's result a flat,
queryable list distinguishing a real Job-tier `MemoryStore` record from a terminal Engineering
record's own inline citations. There is no `dv-harness` CLI verb wired in (`cli.py` untouched, per
this batch's own scope) -- the front door is `python -m dv_harness.memory_lineage lineage --root
<dir> --memory-id <id> [--record <file.json>] [--json]` (exit 0 `FULLY_RESOLVED`, 1
`PARTIALLY_RESOLVED`, 2 `ROOT_UNAVAILABLE`/usage error).

Proven by `dv_harness_tests/test_memory_lineage.py` (20 tests) against REAL production write
paths throughout -- `memory_router.route_and_store()`/`promote_to_organizational()` (with
`OrganizationalMemoryStore.add()` patched only at the literal remote-push seam, the exact idiom
`test_memory_tier_integrity_and_admission.py`'s own
`test_the_earned_promotion_path_still_clears_the_write_boundary_gate` already established),
`MemoryGC.confirm()`, `MemoryConsolidator.from_closed_finding()`, and real
`memory_vault.get_active_provider()`/`.create()` note round trips -- never a hand-typed record.
Negative controls carry the detection power: a bare project mints nothing and reports
`ROOT_UNAVAILABLE`; a dangling `source_engineering_memory_id` is reported rather than dropped; a
real A<->B corroborating-id cycle terminates and is never counted as unresolved; a
`source_finding_id` citation is proven to never attempt resolution as a memory_id; a
RELATED-similarity wikilink is proven excluded from lineage while a genuine bare wikilink beside
it is walked as ambiguous; and confirmation history is proven to retain only the most recent of
three real confirming-evidence submissions. Both the in-process API and a real
`python -m dv_harness.memory_lineage` subprocess are exercised across all three exit codes.
Re-running `test_memory_tier_integrity_and_admission.py`/`test_memory_vault.py`/
`test_memory_dedup_write_path.py`/`test_cross_project_mining.py`/
`test_engineering_confirmation_accumulation.py`/`test_memory_tier_completion.py`/
`test_memory_write_guard_and_job_evidence.py` (203 tests) both before and after this addition
produced byte-identical results (202 passed, 1 pre-existing failure unrelated to memory/lineage
code -- `test_memory_vault.py::test_detect_obsidian_cli_real_probe_reports_not_installed_on_this_machine`,
an environment-detection assertion about this machine's own PATH, reproduced identically before
any of this module's code existed), confirming this addition is genuinely additive and disturbs
no existing memory-tier behaviour.

**Deliberately bounded, and stated rather than implied closed.** (1) It never fixes, resolves, or
arbitrates a dangling reference, a confirmation gap, or an ambiguous vault link -- every honesty
limit is reported, never silently resolved by guessing. (2) The confirmation-event history gap is
a real schema limitation this module discloses rather than closes -- closing it for real would
need `MemoryGC.confirm()` itself to append to a history array instead of overwriting one field, a
change to `memory.py` explicitly out of this item's own additive, read-only scope. (3) It is
REACHED, not WIRED: no `run_stage()`/`advance()` call site or graph node invokes it, and there is
no `dv-harness` CLI verb -- a caller (a human, a dashboard card, or a future engine hook) invokes
it directly.


<!-- S189: moved verbatim from CLAUDE.md original lines 10778-10885 (M4.6 CLAUDE Context Normalization) -->
## Confidence-Calibration Feedback Loop: Weight-Adjustment Proposals, Never a Live Formula Change (2026-09-07)

`confidence_calibration.py` (VI-1) already computes whether this harness's own real Memory
history CONTRADICTS the tier ordering it acts on (CONFIRMED > HIGH > MEDIUM > LOW) --
`FINDING_INVERTED_TIER_ORDER`, over real `MemoryGC.confirm()`/`retract()` outcomes. Nothing
turned that finding into anything actionable: `calibrate()` only ever REPORTS, and its own
CLAUDE.md section already states the module "computes NOTHING about a conclusion itself ... it
only counts real outcomes per tier and reports where the ordering this harness ACTS on is not
the ordering its own history supports." A real inversion had nowhere to go.

This is deliberately not a fix to `inference.score_confidence()`. Per the Evidence Truth Rule, a
weight/threshold change is a production-scoring change like any other and must never be applied
directly on the strength of a calibration report -- it must be PROPOSED as data for a human to
approve through this project's existing controlled-experiment machinery, the same discipline
every other production-behavior change in this harness already follows.

**`confidence_calibration.draft_reweighted_confidence_proposal(report)`** is the propose-as-data
half. `SCORE_CONFIDENCE_CONSTANTS` is a snapshot of `score_confidence()`'s own real formula
constants (`source_weight`, `source_cap`, `evidence_verified_bonus`, `counter_evidence_penalty`,
`consensus_bonus`, `consensus_threshold`, `high_threshold`, `medium_threshold`) --
`assert_score_confidence_constants_current()` re-derives every one of them by PROBING the real,
unmodified `score_confidence()` with controlled synthetic inputs (never by reading or
duplicating its source), and raises loudly the moment a future edit to that function's formula
disagrees with what is recorded here. Called at import, mirroring `assert_tiers_cover_inference_
levels()`'s own self-check discipline one level up, and re-run inside
`draft_reweighted_confidence_proposal()` itself so a drifted constant is caught even by a caller
that never triggers the module's own import path a second time.

`draft_reweighted_confidence_proposal()` reads `report["findings"]` for real
`FINDING_INVERTED_TIER_ORDER` entries. With none, there is no tier-ordering evidence to propose
a re-weighting from (`REWEIGHT_PROPOSAL_NO_INVERSION`) -- never a proposal drafted against
nothing. `TIER_ENTRY_THRESHOLD_CONSTANT` maps only `HIGH`/`MEDIUM` onto the ONE thing a
tier-ordering finding can defensibly propose tightening: the ENTRY BAR for the over-ranked tier
(`high_threshold`/`medium_threshold`), never one of the WEIGHT constants -- reweighting a weight
would change what counts as evidence at all, a materially different (and much larger) claim than
"this tier is currently too easy to reach." `CONFIRMED` is deliberately never addressable: it is
minted by `memory.MemoryConsolidator.from_closed_finding()` behind a procedural bar (single_sim
PASS + regression PASS/NOT_REQUIRED + re-audit CLEAN), never by this formula, so an inversion
naming only CONFIRMED as over-ranked reports `REWEIGHT_PROPOSAL_NOT_ADDRESSABLE` rather than
drafting a proposal that could not possibly fix what it cites. Two or more findings tightening
the SAME constant bump it ONCE, by the single largest bump any one of them alone calls for,
never summed -- piling bumps from several findings pointed at one constant would manufacture a
larger change than any one of them is individually evidence for. A disclosed clamp keeps
`medium_threshold` strictly below `high_threshold` if a bump would ever cross them. The function
performs zero writes anywhere, and its own `disclosure` field states this in words a human
reading the drafted proposal sees directly.

**`capability_evolution.build_confidence_reweight_candidate()` / `file_confidence_reweight_
candidate()`** carry that proposal, verbatim as TEXT, into a real `CapabilityEvolutionCandidate`
through the SAME `build_candidate()`/`persist_candidate()` path `file_repeated_failure_
candidate()` already uses -- the one Blackboard topic and the one Working Memory audit trail
every other candidate in this module uses, never a parallel mechanism. `trigger_type` is
`INTERNAL_AUDIT` (section 64's own gap-detection source for an internal calibration finding).
Exactly like the repeated-failure coupling, it files at `DISCOVERED` only: all six `existing_*`
search slots are honestly `NOT SEARCHED` (no repository search is performed), so
`overlap_status`/`recommendation` derive to `UNKNOWN` and the candidate schema's own `allOf`
structurally pins `current_status` to `DISCOVERED`/`EVIDENCE_GATHERING`/`REJECTED` -- reaching
`PROPOSED` needs a real `research-architect` pass, exactly as it does for every other auto-filed
candidate this module produces. `evidence_refs` is one entry per CITED FINDING (not merely per
constant name), so a genuinely new inversion pointing at an already-cited constant still grows
the evidence set and correctly re-files as `NEW_EVIDENCE` rather than being silently treated as
unchanged.

The candidate's own `proposed_action`/`experiment_plan`/`benchmark_plan` name, in full, the
ONLY path this proposal could ever become a real edit: a human moves it to
`EXPERIMENT_APPROVED`; `capability_evolution.run_controlled_experiment()`'s existing `mutation`
argument rewrites `inference.py`'s constants to the proposed values inside the TREATMENT copy of
an isolated fixture ONLY (never this live project, never `inference.py`'s real file);
`run_shadow_replication()` clears the real stability window; a human decision at
`HUMAN_APPROVED` -- all four steps are the existing, unmodified section 61 LEVEL B -> LEVEL C
path, and nothing in this coupling performs any of them. `HumanApprovalRequiredError`,
`ProductionWriteNotAuthorizedError`, and the real `ControlPlane` approval check are unchanged
and unweakened, proven directly against a filed candidate.

**`inference.py`'s live formula was not touched by this item**, per its own explicit instruction.
Confirmed three ways: `git status` never lists it as modified; `assert_score_confidence_
constants_current()` PROBES the real function rather than importing/duplicating its numbers, so
this module can never itself apply a re-weighting even by accident; and two dedicated tests -- one
per module -- snapshot `inference.py`'s real bytes on disk before and after calling every new
function and assert byte-for-byte equality.

Proven by 10 new tests in `dv_harness_tests/test_confidence_calibration.py` (45 total, the
original 35 untouched and still passing) -- the constants self-check and its drift-detection
negative control (mirroring `test_a_tier_invented_here_or_dropped_from_inference_fails_
loudly()`), the required no-inversion negative control, the real HIGH>MEDIUM and MEDIUM>LOW
worked examples, the two-findings-one-constant-one-bump proof, the CONFIRMED-only
not-addressable case, a mixed report proving an unaddressable finding is carried alongside a
drafted proposal rather than dropped, the medium/high clamp, and the file-untouched proof -- and
16 new tests in `dv_harness_tests/test_capability_evolution_confidence_reweight.py`, driven
against a real `MemoryStore` populated through the REAL `MemoryGC.confirm()`/`retract()`
writers and a real `confidence_calibration.calibrate()` report end to end, never a hand-shaped
stand-in: the two negative controls (no proposal, CONFIRMED-only proposal, both filing nothing),
the real persisted `DISCOVERED` state and its Working Memory audit record, the six-slot honesty
check, confidence recomputed rather than self-reported, candidate-id stability across cycles
with genuine evidence accumulation, the human-never-dragged-back and skip-governance-states
walls, the untouched `ControlPlane` boundary, the Working-Memory-tier-only guarantee, and one
full end-to-end run through both modules together.

**Disclosed residual**: this closes the DISCOVERY-and-PROPOSAL half only, exactly like its
repeated-failure sibling. It is REACHED, not WIRED -- no `run_stage()`/`advance()` call site or
engine hook invokes `draft_reweighted_confidence_proposal()`/`file_confidence_reweight_
candidate()` yet; a caller (a future cross-loop coupling, or a human running
`dv-harness confidence-calibration report` by hand) invokes them directly. A drafted proposal
that reaches `EXPERIMENT_APPROVED` still needs a human-supplied isolated fixture to run
`run_controlled_experiment()` against -- nothing here supplies one automatically, matching this
project's own "never run a live simulator, build, regression, or LSF job" boundary for this
item.


<!-- S190: moved verbatim from CLAUDE.md original lines 10886-10905 (M4.6 CLAUDE Context Normalization) -->
## ConsensusResult Type + score_confidence_with_consensus(): a Split Vote Scores Differently From a Unanimous One (2026-09-07)

`inference.score_confidence()`'s `multi_agent_consensus_count` parameter is a bare int: `>= 2` grants a flat `+2` bonus regardless of whether those agents unanimously agreed or split 3-2 with active disagreement -- both currently score identically. `dv_harness/inference.py` gained two additive, opt-in additions closing that gap, with `score_confidence()` itself, its exact 4-positional-int signature, its exact current formula, and every existing caller's behavior left completely untouched (a dedicated negative-control test re-asserts `score_confidence()`'s documented HIGH/MEDIUM/counter-evidence-capped outputs byte-for-byte after the change, and confirms the old return dict carries no `consensus` key).

**`ConsensusResult`** (a frozen dataclass: `agree_count`, `disagree_count`, `abstain_count=0`, `dissenting_claims: Tuple[DissentingClaim, ...] = ()`) is the typed replacement for the bare int, carrying `total_votes`, `is_unanimous` (>=2 agents, zero disagreement -- the same `>=2` floor `score_confidence()`'s own bonus threshold already uses), and `is_split` (both agree_count and disagree_count > 0) as properties. Each `DissentingClaim` (`agent`, `claim`, `evidence=""`) requires a non-empty `agent` and `claim`; `ConsensusResult` refuses to be constructed with more `dissenting_claims` than its own `disagree_count` (an uncited dissent can be recorded with `evidence=""`, but a dissent cannot be claimed for an agent who did not disagree).

**`score_confidence_with_consensus(independent_sources_count, evidence_refs_verified, counter_evidence_count, consensus_result)`** is a NEW, SEPARATE function -- not a modification of `score_confidence()` -- that reuses the identical base formula (source count capped at 3 and doubled, `+2` for verified evidence, `-3` per counter-evidence entry, the same HIGH/MEDIUM/LOW thresholds, and the same counter-evidence safety floor that never lets an unaddressed counter-evidence entry coexist with a reported HIGH) and replaces only the multi-agent-consensus term with a consensus-aware one derived from the real `ConsensusResult`:

- fewer than 2 total votes, or `agree_count - disagree_count <= 0` (a tie or a disagreement majority): `+0` -- exactly `score_confidence()`'s own `< 2` case, never a positive bonus for a vote that did not actually reach agreement.
- a real UNANIMOUS consensus (`>= 2` agents, zero disagreement): `+2` -- byte-identical in magnitude to `score_confidence()`'s own `>= 2` bonus, so a caller whose votes happen to always be unanimous sees no score change by switching to the new function.
- a real SPLIT vote with a genuine, positive net agreement (both sides > 0, agreements outnumber disagreements): `+1` -- real corroborating signal, but deliberately weaker than a unanimous one, so the two can never score identically.

The returned dict keeps `score_confidence()`'s exact `{"level", "score", "capped_by_counter_evidence"}` shape and adds one new key, `"consensus"`, carrying the vote breakdown (`agree_count`/`disagree_count`/`abstain_count`/`total_votes`/`is_unanimous`/`is_split`), the actual `consensus_bonus_applied`, and every cited `dissenting_claims` entry (`agent`/`claim`/`evidence`) -- so a caller looking at a MEDIUM-not-HIGH result can see exactly who disagreed and why, not merely that some agent did.

**Purely additive and opt-in, per the project's backward-compatibility rule.** No existing caller of `score_confidence()` (`engine.py`, `capability_evolution.py`, `memory_router.py`, `lsf_client.py`, `system_resource_inventory.py`, `system_resource_registry.py`, `remote_control.py`, `system_failure_triage.py`, `user_correction_trigger.py`, `coverage_stall_capability_discovery.py`, and every test that exercises them) was changed, and nothing requires migrating to the new function -- it is available for a future caller that wants split-vs-unanimous multi-agent-review scoring, e.g. a multi-agent evidence-consensus review step, without any change to today's single-int callers. No production scoring weight or threshold was applied directly to any existing gate; the new consensus-bonus constants live only inside this new, entirely opt-in sibling path.

Proven by `dv_harness_tests/test_inference.py` (40 tests, up from 27 -- every original test unchanged and still passing): `ConsensusResult`/`DissentingClaim` construction and validation (negative counts, empty agent/claim, dissenting-claims-exceeding-disagree-count); the unanimous case matching the old bonus's exact magnitude; the split-vote-scores-lower-than-unanimous proof (this item's own core requirement); dissenting evidence round-tripping into the report; the tied/disagreement-majority/no-data cases all scoring identically at zero bonus (the required negative control -- a vote that did not actually reach agreement must never earn a positive bonus); the counter-evidence safety floor proven to still hold under the new path; and input-type rejections (a bare int passed as `consensus_result`, negative source/counter-evidence counts, a non-bool `evidence_refs_verified`). `dv_harness_tests/test_confidence_vocabulary_separation.py` and `dv_harness_tests/test_confidence_calibration.py` (91 combined) and `dv_harness_tests/test_capability_evolution_confidence_reweight.py` (16, the module that most aggressively cross-checks `score_confidence()`'s own numeric constants against a hand-copied table) were re-run and stay fully green, confirming `score_confidence()`'s existing behavior is unchanged for every real caller in the codebase.

**Disclosed residual**: this closes the TYPE and the new SCORING PATH only. Nothing in the engine currently calls `score_confidence_with_consensus()` -- it is a REACHED capability (importable and directly usable), not yet WIRED into any multi-agent evidence-review call site. Wiring a real multi-agent consensus review step (e.g. a future `_score_root_cause_confidence()`-style caller that has genuine multiple-agent vote data) to build a `ConsensusResult` and call this function instead of `score_confidence()` is a deliberate follow-up, left for a pass that owns that call site's own real evidence shape.


<!-- S191: moved verbatim from CLAUDE.md original lines 10906-10965 (M4.6 CLAUDE Context Normalization) -->
## Value-of-Information Evidence-Gathering Ranking: `rank_evidence_by_information_value()` (2026-09-07)

`dv_harness/inference.py`'s `identify_gap()` already computes the pure set-difference of what a
single hypothesis still needs; nothing ranked which of several MISSING evidence categories, across
several COMPETING hypotheses, would most reduce uncertainty about which hypothesis is actually
correct -- an autonomous agent's own choice of next evidence-gathering ACTION mid-debug, distinct
from `intake_question_priority.py`'s already-in-flight ranking of PENDING QUESTIONS put in front of
a human (gated on confidence/criticality, scored by
`blocking_value*downstream_impact*expected_confidence_gain/user_effort`, with a do-not-ask policy
and batching for a person's attention). A repo-wide grep for `value_of_information`/`VOI`/
`reduce_uncertainty`/`evidence_gathering` before this change matched nothing relevant.

`inference.rank_evidence_by_information_value()` is that missing ranking, added ADDITIVELY right
beside `identify_gap()` -- that function is completely untouched (proven by a dedicated negative
control re-running its own documented case) and is REUSED verbatim (called, never re-derived) to
compute each hypothesis's own missing categories; every existing `identify_gap()` call site and
test is unaffected.

**Real value-of-information math, not a naive count.** For every category missing from at least one
hypothesis, two deterministic factors combine: `discrimination = 4 * p * (1 - p)`, where `p` is the
fraction of hypotheses that REQUIRE the category and are currently missing it (out of every
hypothesis that requires it at all) -- maximal (1.0) when a category splits its applicable
hypotheses roughly in half, and 0 when it is missing from ALL of them (gathering it would help
every hypothesis equally, so it cannot discriminate which one is right) or missing from NONE. This
is the whole point of the mechanism, proven as the suite's own negative control: a category
universally missing across all 4 competing hypotheses (a naive "most hypotheses need this" count
would rank it #1) correctly scores `discrimination = 0.0`, while a category missing from exactly
half of them scores maximal discrimination and is ranked first instead. The second factor,
`uncertainty_weight`, is the average urgency (`URGENCY_BY_CONFIDENCE_LEVEL`: LOW=3, MEDIUM=2,
HIGH=1, unspecified treated as MEDIUM) of only the hypotheses currently missing the category,
normalized into `(0, 1]` -- so the identical discriminating category scores higher when it matters
to LOW-confidence hypotheses than to HIGH-confidence ones. `voi_score = discrimination *
uncertainty_weight`.

**Evidence Truth Rule, applied to a ranking rather than a scoring weight.** Nothing here is applied
directly to production behavior: this is a pure, read-only ranking function over caller-supplied
hypothesis data -- it writes no state, files no question, runs no build/gate/approval, and there is
no stage gate. It never touches `score_confidence()`'s own weight/threshold formula (a different,
untouched mechanism); if a future pass wanted to route a proposed weight change through
`capability_evolution.py`'s controlled-experiment machinery, that would be a separate, human-approved
change, not something this ranking function does on its own.

Reachable directly as `inference.rank_evidence_by_information_value(hypotheses)`; there is no
`dv-harness` CLI verb or `gates.py` entry -- a REACHED capability, not a WIRED one, matching this
project's own established convention for a small, standalone additive function.

Proven by 14 new tests in `dv_harness_tests/test_inference.py` (54 total in that file, the original
40 untouched and re-run clean before and after this change as the required baseline/regression
check): the empty-hypotheses degenerate case; the headline discrimination-vs-universal-need negative
control described above; the uncertainty-weight-from-confidence-level case (identical discrimination,
different `voi_score` from LOW vs. HIGH confidence); the unspecified-confidence-defaults-to-MEDIUM
case; `hypotheses_applicable`/`hypotheses_missing` list correctness (including a hypothesis that
never required the category never appearing in either list); a fully-supplied category never being
ranked at all (identify_gap()'s own exclusion surviving into the ranking); deterministic tie-breaking
by category name; propagation of `identify_gap()`'s own input validation; five invalid-input negative
controls (non-list, non-dict entries, missing/blank `hypothesis_id`, an unrecognized confidence
level); and the required negative control proving `identify_gap()`'s own documented behavior is
completely unaffected by this new sibling function's existence. `python -m pytest
dv_harness_tests/test_inference.py -q` -> `54 passed`.


<!-- S192: moved verbatim from CLAUDE.md original lines 10966-11097 (M4.6 CLAUDE Context Normalization) -->
## Hypothesis-Generation Bias Correction From Retracted Hypotheses (2026-09-07)

`inference.detect_hypothesis_generation_bias()` is the item's own worked example made real:
"hypotheses citing only a symptom register and never a control register are wrong more often" is
no longer a claim anyone would have to eyeball a project's own history to check -- it is now one
real, cited finding this function reports IF, and only if, a project's own retracted-vs-not
hypothesis corpus actually shows it. REUSE OVER REINVENT, checked before writing anything: a
repo-wide grep for `hypothesis.*bias`/`hypothesis_shape`/`generation_bias` matched nothing.
`memory.py`'s `MemoryGC.retract()` already records, per real memory record, that "the record was
found to be wrong outright" (its own docstring), with a real cited `retraction_reason`;
`confidence_calibration.py` already reads that same real vocabulary back to ask a DIFFERENT
question (does a CONFIDENCE TIER's own track record match the ordering this harness acts on).
Nothing asked this question -- does the SHAPE of a retracted root-cause hypothesis (which real
evidence categories its own citations covered) predictably correlate with it later being found
wrong, independent of which confidence tier it was assigned.

**Two functions, added additively right after `rank_evidence_by_information_value()` -- the
existing 40 (later 54) tests in `test_inference.py` were re-run clean both before and after this
change, per the mandatory baseline/regression rule for a core file.** `detect_hypothesis_generation_bias(hypotheses, *, min_group_size=5, margin=0.2)`
is pure math over a caller-supplied list of `{hypothesis_id, retracted, evidence_categories_cited}`
dicts -- no I/O, mirroring `rank_evidence_by_information_value()`'s own pure-function shape one
function above it in the same file. `collect_hypothesis_shapes(root, *, store=None)` +
`hypothesis_shape_from_record(record)` are the real-data bridge: a deferred `from .memory import
MemoryStore` (so `inference.py` itself stays dependency-free of the rest of the harness for every
caller that only ever wants its pure math -- the same reason `confidence_calibration.calibrate()`'s
own `store` parameter exists) reads every real `HYPOTHESIS_RECORD_KINDS` (`root_cause`/
`verified_fix`/`debug_lesson` -- `memory_router.py`'s own `ENGINEERING_REUSABLE_CLAIM_FIELDS`
vocabulary, reused verbatim, never a separately invented kind list) record in a project's
`MemoryStore`, and converts each one's real, persisted `status` field into `retracted` (True iff
it equals the literal `"RETRACTED"` `MemoryGC.retract()` itself writes -- `SUPERSEDED` is
deliberately excluded, since being superseded says a better record now exists, not that THIS
hypothesis's own evidence shape is what made it wrong, while a retraction is squarely about the
claim itself being wrong).

**No current production writer in this repository persists a category-keyed evidence shape as a
structured field -- confirmed by reading `engine.py`'s real `verified_fix`/`root_cause`/
`debug_lesson`-kind record construction before writing a line of this -- but one real writer
already CAN.** `engine._promote_experience_knowledge()` (EXPERT_FEEDBACK_LOOP's
`experience_knowledge_gate` PASS) already writes the agent's own free-text `evidence` field
verbatim onto the stored record (`"evidence": block.get("evidence")`), and that gate script
(`tools/verification_flow/experience_knowledge_gate.py`) enforces only that the field is truthy --
never a shape. So a category-keyed dict (`{"symptom_register": "...", "control_register": "..."}`)
is a real, legal, unenforced value that field can already hold today.
`hypothesis_shape_from_record()` reads it back the same "category name -> truthy citation"
convention `engine.py`'s own `root_cause_evidence_gate` handling already uses for its four FIXED
`ROOT_CAUSE_EVIDENCE_CATEGORIES` (`[c for c in categories if block.get(c)]`), generalized here to
whatever category keys a project's own evidence dict actually declares -- never a hardcoded
vocabulary, and an `evidence` field that is not a dict (free text, a list, absent -- every real
record this repository's own writers produce today) reports an honestly EMPTY category set, never
a guess: this record's shape was simply never structured this way, which is a different fact from
"it cited nothing". This is the same honest "REACHED, not yet WIRED with real data" disclosure
`user_correction_trigger.py`'s own module docstring already makes for `MemoryGC.retract()`/
`supersede()` themselves having zero production callers today -- the mechanism activates the
moment a real project's `evidence` field is shaped this way, proven here against a real
`MemoryStore`/`MemoryGC` (never hand-written JSON standing in for either).

**Two independent, complementary comparisons, both gated on `min_group_size` in EVERY compared
group so a rate is never computed -- in either direction -- from too small a sample.** (1)
PER-CATEGORY: for every category cited by at least one hypothesis, splits the corpus into
hypotheses that DID cite it and hypotheses that did NOT, and reports a
`FINDING_EVIDENCE_CATEGORY_BIAS` finding when the two groups' retraction rates differ by more than
`margin`, naming which direction the correlation runs (`DIRECTION_ABSENCE_CORRELATES` -- the shape
of the item's own worked example -- or `DIRECTION_CITING_CORRELATES`, the opposite: over-reliance
on a noisy/unreliable category). (2) EXACT-SHAPE: for every distinct exact set of cited categories,
compares that shape's own retraction rate against every OTHER hypothesis's, reporting a
`FINDING_HYPOTHESIS_SHAPE_BIAS` finding when citing EXACTLY that combination -- and nothing else --
correlates with more retractions than the rest of the corpus. A category or shape that could not
be compared (either group below `min_group_size`) is still reported, under
`categories_insufficient`/`shapes_insufficient`, so a reader sees the whole picture rather than a
silently narrowed one -- mirroring `confidence_calibration._tier_report()`'s own
`calibratable`/`insufficient_reason` transparency one module over.

**`min_group_size=5`/`margin=0.2` are derived, not chosen**, the identical "smallest N at which
1/N does not exceed the resolution band" reasoning `confidence_calibration.
MIN_DETERMINATE_OUTCOMES_PER_TIER`/`RELIABILITY_RESOLUTION` already state for themselves --
independently re-derived here (never imported: `confidence_calibration.py` already imports FROM
`inference.py`, so the dependency can only run this direction) at a coarser 0.2 band rather than
that module's 0.1, because a retracted-HYPOTHESIS corpus is real-world sparser than a whole memory
store's tier-outcome corpus, and requiring that module's own 10-per-group bar here would make this
analysis report `INSUFFICIENT_HISTORY` on every real project that has not yet accumulated a large
hypothesis history.

**Four honest statuses, matching this project's own worst-wins/never-fabricate-precision
discipline**: `NOT_AVAILABLE` (`hypotheses` is empty -- nothing to analyze, mirroring
`rank_evidence_by_information_value()`'s own "an empty list is not an error" rule);
`INSUFFICIENT_HISTORY` (hypotheses exist, but no category and no exact shape ever reached
`min_group_size` in both of its compared groups -- a real, honest answer about a project's current
history, not a failure); `NO_BIAS_DETECTED` (at least one comparison was possible, and none showed
a margin exceeding `margin`); `BIAS_DETECTED` (at least one real finding).

**NEVER auto-suppresses or blocks a future hypothesis matching a flagged pattern -- reporting
only, and this is a structural fact about this change, not merely a documented intent.** This
function is a pure computation returning a dict; it is called from nowhere in `engine.py`,
`gates.py`, or any stage-gate/scoring path this pass touches -- a REACHED capability (importable
directly, `from dv_harness import inference; inference.detect_hypothesis_generation_bias(...)`),
not a WIRED one, the same disclosed shape `rank_evidence_by_information_value()`'s own CLAUDE.md
section states for itself one entry above this one. Per the Evidence Truth Rule, a finding here
must never be applied directly to production scoring: acting on one (e.g. auto-penalizing a future
hypothesis whose shape matches a flagged pattern) would be exactly the kind of
production-scoring-policy change that must be routed through `capability_evolution.py`'s existing
controlled-experiment machinery for a human to approve, exactly like every other production-behavior
change in this project -- this function computes descriptive evidence only, it decides nothing, and
it never touches `score_confidence()`'s own formula or constants (a completely separate, untouched
mechanism, proven directly by a dedicated negative-control test re-running `score_confidence()`'s
own documented HIGH-case example unchanged after calling this function).

Proven by 19 new tests appended to `dv_harness_tests/test_inference.py` (73 total, the original 54
re-run clean before and after this change as the required baseline/regression check): the
empty-input `NOT_AVAILABLE` case; a too-small-sample `INSUFFICIENT_HISTORY` case (including the
transparency proof that the under-powered comparison is still listed, not silently dropped); the
headline worked-example proof (`_biased_corpus()`, a synthetic corpus where hypotheses missing
`control_register` are genuinely retracted more often, surfacing `DIRECTION_ABSENCE_CORRELATES`
with the exact real counts/rates/margin, alongside the negative-control proof that the
universally-cited `symptom_register` category is correctly reported `categories_insufficient`
rather than a spurious 0%-vs-something comparison); the opposite `DIRECTION_CITING_CORRELATES`
case; a no-finding case where the two rates sit within `margin` of each other (proving the module
does not manufacture a finding out of noise); an exact-shape (`FINDING_HYPOTHESIS_SHAPE_BIAS`)
case a per-category view alone could not surface as cleanly; six parametrized invalid-input
negative controls (non-list, non-dict entries, blank/duplicate `hypothesis_id`, a non-bool
`retracted`, a non-list `evidence_categories_cited`) plus `min_group_size`/`margin` validation
(including the bool-rejected-as-not-a-number case); the required negative control proving
`score_confidence()` is untouched after a call; `hypothesis_shape_from_record()`'s real
RETRACTED/SUPERSEDED distinction and its falsy-dict-value-never-counts-as-cited proof;
`hypothesis_shape_from_record()` refusing a record with no `memory_id`; and
`collect_hypothesis_shapes()` driven against a REAL `dv_harness.memory.MemoryStore`/`MemoryGC` on
disk -- a real `root_cause` record genuinely retracted via `MemoryGC.retract()`, a real
`verified_fix` record left `ACTIVE`, a `job_failure`-kind record proven correctly EXCLUDED (not a
root-cause-shaped kind, and it carries no `root_cause` field), the collected shapes fed straight
into `detect_hypothesis_generation_bias()` with no adaptation, and the no-`store`-supplied path
constructing its own real `MemoryStore`. `python -m pytest dv_harness_tests/test_inference.py -q`
-> `73 passed`.


<!-- S193: moved verbatim from CLAUDE.md original lines 11098-11212 (M4.6 CLAUDE Context Normalization) -->
## Meta-Reasoning: Sizing Evidence-Gathering Effort to Question Difficulty/Stakes (2026-09-07)

Nothing in this repo answered a real, recurring question an autonomous agent faces before it starts
gathering evidence for a claim: does a question THIS SHAPED typically warrant one quick pass, or a
real multi-agent effort? `inference.recommend_evidence_gathering_effort()` closes that gap, added
ADDITIVELY at the end of `inference.py` -- every existing function/constant in that file is
byte-for-byte unchanged (verified: the pre-existing 73-test baseline was re-run both before and after
this change and stays green).

**REUSE OVER REINVENT, on both of this item's own named signals -- neither is re-derived.**
`source_authority_order_validation.py` (this same batch's own sibling item, already real and tested)
already answers whether `source_authority.AUTHORITY_ORDER`'s fixed 9-level order actually matches
which side a human has picked in practice over this project's real, answered Tier-3 conflict
escalations; its own `status`/`mismatches`/`evaluable_cases` ARE this project's real CONTENTIOUSNESS
history, called (`build_report(root).to_dict()`) rather than re-implemented. The second signal --
"any qualified_conclusion domain with a track record of wrong hypotheses" -- has no existing
per-domain mechanism anywhere in this repo (`rca_ontology.py`'s own aggregation groups by root-cause
CATEGORY and by failure SIGNATURE, never by protocol/domain; `confidence_calibration.py` groups by
CONFIDENCE TIER, never by domain), so this item adds the missing DOMAIN axis as a direct, disciplined
extension of this file's OWN `detect_hypothesis_generation_bias()` two-group comparison (documented
in the section immediately above this one) rather than inventing a fourth statistical method:
`domain_wrong_hypothesis_track_record()` reuses that function's own `MIN_HYPOTHESES_PER_COMPARISON_
GROUP`/`HYPOTHESIS_BIAS_MARGIN` constants VERBATIM (the identical sparse-domain floor and
resolution-band margin that module already derived and justified), applied along a DOMAIN axis
(protocol) instead of an evidence-CATEGORY axis. `domain_hypothesis_shape_from_record()` mirrors
`hypothesis_shape_from_record()`'s own real `retracted` derivation (`status ==
HYPOTHESIS_RETRACTED_STATUS`, the literal value `MemoryGC.retract()` itself writes) exactly, adding
only the one field that function deliberately strips -- the record's own real `protocol`.
`collect_domain_hypothesis_shapes()` mirrors `collect_hypothesis_shapes()`'s own real-store-reading
shape (same kinds, same `if r.get("root_cause")` eligibility filter, same deferred `from .memory
import MemoryStore` so this file's own stated "dependency-free for every caller that only ever wants
its pure math" promise is preserved), with one improvement over its sibling: it checks
`cross_project_mining.has_memory_store()` BEFORE ever constructing a `MemoryStore` -- that
constructor `mkdir()`s the whole tier tree and writes an empty `index.json` (the same real side
effect `confidence_calibration.py`/`cross_project_mining.py` already document and guard against for
the identical reason), and a pure read for a project's own domain track record must never bring a
store into existence merely by asking about it.

**Two honest per-signal mappings, folded worst-wins -- never averaged, the same composite-gate
discipline this project applies everywhere else.** Each signal independently resolves to one of
`EFFORT_LEVELS = (MINIMAL, STANDARD, THOROUGH)`: `ORDER_DIVERGES_FROM_PRACTICE`/
`BIAS_STATUS_BIAS_DETECTED` -> THOROUGH (real evidence this class of question, or this domain, is
genuinely contentious/error-prone); `ORDER_MATCHES_PRACTICE`/`BIAS_STATUS_NO_BIAS_DETECTED` ->
MINIMAL (real evidence the opposite); anything else -- no signal supplied at all,
`NO_EVALUABLE_CASES`, `BIAS_STATUS_INSUFFICIENT_HISTORY`, `BIAS_STATUS_NOT_AVAILABLE` -- -> the
NEUTRAL STANDARD baseline. Absence of a real signal is deliberately NEVER read as "safe to use fewer
agents": the overall recommendation is `max()` of the two signals' own levels, so a MINIMAL-resolving
signal paired with an unsupplied (STANDARD) one still reports STANDARD overall, and reaching an
overall MINIMAL requires BOTH signals to independently agree the question is low-risk -- proven
directly by a dedicated test. `EFFORT_LEVEL_MIN_INDEPENDENT_AGENTS` (`MINIMAL`:1, `STANDARD`:2,
`THOROUGH`:3) makes THOROUGH's floor of 3 this project's own real Core Operating Rule made concrete:
"Important DUT/PHY/Register/VIP changes require Multi-Agent evidence acquisition plus independent
synthesis."

**A RECOMMENDATION ONLY, and this is structural, not merely narrated.** `recommend_evidence_
gathering_effort()` is a pure function returning a dict -- it never dispatches an agent, never runs
a build/regression/LSF job, and never writes any state, memory record, or Blackboard topic; every
returned result carries a `disclosure` field stating this explicitly, and one test asserts, by
reading this function's own source, that no dispatch/write-shaped token (`subprocess`, `Popen`,
`run_stage`, `add_question`, a real store-mutating call) appears in it at all. It never proposes
changing `score_confidence()`'s own formula/weights/thresholds, and per the Evidence Truth Rule it is
never itself applied to production scoring -- a weight/threshold change proposal still has to be
routed through `capability_evolution.py`'s controlled-experiment machinery for a human to approve,
exactly like every other production-behavior change in this project; this function only sizes an
ADVISORY recommendation, and whether/how a caller/Workflow-script acts on it is entirely that
caller's own decision.

**Deliberately bounded, and stated rather than implied closed.** (1) Both real signals may be
supplied pre-computed (for a caller that already ran the underlying analysis itself, or for a unit
test), or this function computes them itself from a real project `root` -- but the domain signal is
computed ONLY when a real `domain` is also supplied; with no domain named there is nothing to
compare against the rest of the corpus, so that signal honestly stays absent rather than guessing a
domain from `root` alone. (2) `domain_wrong_hypothesis_track_record()` answers one specific,
one-directional question -- is this domain WORSE than the rest of the corpus; a domain scoring
BETTER than average is also honestly `BIAS_STATUS_NO_BIAS_DETECTED`, never read as a reason to
REDUCE the recommended effort, which would need separate, dedicated justification this function does
not attempt. (3) There is no `dv-harness` CLI verb and no engine call site -- a REACHED capability
(`from dv_harness import inference; inference.recommend_evidence_gathering_effort(...)`), not a
WIRED one, matching this project's own established convention for a small, standalone additive
function; a future Workflow script deciding how many agents to actually dispatch for a given
question is the natural integration point, and is explicitly out of this item's own scope.

Proven by 34 new tests appended to `dv_harness_tests/test_inference.py` (107 total in that file, the
original 73 re-run clean before and after this change as the required baseline/regression check):
`domain_hypothesis_shape_from_record()`'s protocol-preserving/RETRACTED-vs-SUPERSEDED/missing-
`memory_id` cases; `collect_domain_hypothesis_shapes()` driven against a REAL `dv_harness.memory.
MemoryStore`/`MemoryGC` on disk (protocol preserved through a real retraction), the required
negative control that a bare project with no memory store returns an empty list and creates NOTHING
on disk, and the constructs-its-own-store path; `domain_wrong_hypothesis_track_record()`'s full
status vocabulary (`NOT_AVAILABLE`/`INSUFFICIENT_HISTORY`/`NO_BIAS_DETECTED`/`BIAS_DETECTED`)
including the headline worse-than-average proof, the required negative control that a
BETTER-than-average domain is also `NO_BIAS_DETECTED` (never read as a reason to reduce effort), the
required negative control that a hypothesis with no recorded domain contributes to NEITHER
comparison group, case-insensitive domain matching, and validation refusals for a non-list/non-dict/
non-bool-`retracted`/blank-domain/invalid-`min_group_size`/invalid-`margin` input; and
`recommend_evidence_gathering_effort()`'s full behavior -- the neutral-baseline-with-no-signals case,
both real signals' THOROUGH/MINIMAL/STANDARD mappings in isolation, the worst-wins fold (a single
THOROUGH-worthy signal outranking an otherwise-clean MINIMAL one) and its converse (an overall MINIMAL
requiring BOTH signals to independently agree), the never-dispatches-or-writes source-level proof,
the domain-omitted-never-computes-a-domain-signal proof, and three full end-to-end integration tests
-- a bare project root staying neutral and creating nothing on disk, a REAL `source_authority.
escalate_conflict()` + a REAL human-override `answer_question()` driving the recommendation to
THOROUGH via `build_report(root)` with no pre-computed report supplied, and a REAL `MemoryStore`/
`MemoryGC` fixture (5 USB3 hypotheses, 4 retracted, vs. 10 clean PCIe hypotheses) driving the
recommendation to THOROUGH via `collect_domain_hypothesis_shapes()`/`domain_wrong_hypothesis_track_
record()` with no pre-computed report supplied either. `python -m pytest
dv_harness_tests/test_inference.py -q` -> `107 passed`. Re-run alongside the directly-adjacent
integration suites this same session -- `test_source_authority_order_validation.py`,
`test_confidence_calibration.py`, `test_cross_project_mining.py` (107 tests combined),
`test_inference_engine_wiring.py`, `test_react_inference_wiring.py`,
`test_qualified_conclusion_closure_gate.py` (31 tests combined, driving real `DVHarness` stage runs
over the real shipped graph) -- all pass unchanged, confirming this purely-additive change disturbs
none of `inference.py`'s existing real callers (23 files import it, none of them touched).



<!-- S201: moved verbatim from CLAUDE.md original lines 11380-11452 (M4.6 CLAUDE Context Normalization) -->
## Context-Scoped Validity: Optional `applicability_context` on Memory Records (2026-09-07)

`MemoryGC.confirm()`/`retract()` were unconditionally GLOBAL: any record whose
`memory_id` resolved was confirmed/retracted in full, with no way to express
that a finding only applies under one VIP release, protocol version, or
similar scope. This is a PURE, ADDITIVE extension of the existing 5-value
status vocabulary's semantics (ACTIVE/DEPRECATED/SUPERSEDED/RETRACTED/
NEEDS_REVALIDATION are completely unchanged -- no sixth status value is
introduced) -- never a new vocabulary, exactly as this item's own scope
required.

**Two additive pieces, both opt-in.** (1) `MemoryStore.add()` now sets
`mem.setdefault("applicability_context", None)` -- a record may declare what
it is scoped to (e.g. `{"vip_release": "R-2020.12"}`, `{"protocol_version":
"3.0"}`), and every record that never sets this (the overwhelming majority,
and every record this codebase's own real writers already produce) keeps the
honest default `None`, which is what keeps it globally confirmable/
retractable. (2) `MemoryGC.confirm()`/`retract()` each gained a new,
OPTIONAL, keyword-only `context` parameter. **Omitting it -- every single
pre-existing call site in this codebase, none of which was edited --
preserves the exact old unconditional-global behavior**, proven directly by
a dedicated backward-compatibility test for each of confirm()/retract(),
covering both an unscoped record and a scoped one.

**The matching rule is deliberately permissive, not exact-dict-equality.**
`_context_compatible(record_context, query_context)`: a record with no
declared context, or a caller with no query context, is always compatible
(global). Two contexts are INCOMPATIBLE only when they explicitly assert
DIFFERENT values for the SAME key -- a key present in only one side is never
treated as a mismatch, since neither side made a claim about it. A record
scoped only to `{"protocol_version": "3.0"}` therefore still confirms under a
caller context additionally naming `{"vip_release": "R-2020.12"}`, since the
record never claimed anything about vip_release either way.

**A scope mismatch is a real no-op, never a partial mutation.** When a
caller supplies `context=` and it disagrees with the record's own declared
`applicability_context` on a shared key, `confirm()`/`retract()` mutate
NOTHING and return `False` -- the identical return shape an unresolved
`memory_id` already produced, so no existing caller's truthy/falsy check
needs to change. This is verified to also suppress `confirm()`'s existing
`NEEDS_REVALIDATION -> ACTIVE` restoration on a scope-mismatched call
specifically (a matching-context companion test proves that restoration
still fires correctly when the scope agrees).

Proven by `dv_harness_tests/test_memory_context_scoped_validity.py` (21
tests, all against a real `MemoryStore`/`MemoryGC` on a real temp directory,
never a hand-shaped record): the pure `_context_compatible()` matching rule
(both-None, record-only, query-only, matching key, disagreeing key, unshared
keys never mismatching, multi-key partial disagreement); `MemoryStore.add()`
defaulting and preserving the new field; the two required backward-
compatibility negative controls (context param omitted ignores a declared
scope entirely, for both `confirm()` and `retract()`); matching-context
success and mismatched-context real-no-op behavior for both methods,
including direct re-reads proving no mutation occurred on mismatch (not
merely that the return value was `False`); the `NEEDS_REVALIDATION`
restoration suppression/still-fires pair; an unrelated extra key in the
caller's context never blocking a match; and unresolved-`memory_id` handling
unaffected by the new parameter's presence or absence.

**Deliberately bounded, and stated rather than implied closed.** (1) This
touches `MemoryGC.confirm()`/`retract()` only -- `CornerCaseLibrary`'s own,
separately-defined `confirm()`/`retract()` methods (a different class, a
different backing store) were left untouched, since the item's own scope
names `MemoryGC` specifically and extending a second class was not part of
the smallest safe additive slice this pass closed. (2) There is no CLI verb
or gate wired to pass `context=` from a real caller yet -- a REACHED
capability (both methods are directly callable with the new parameter today),
not a WIRED one; a future caller (e.g. a VIP-release-aware confirmation flow)
would supply `context=` at its own call site. (3) `_context_compatible()` is
a private helper (not part of the public API) since this item's own scope
is the two `MemoryGC` methods, not a general-purpose context-matching
utility for other modules to import.


<!-- S202: moved verbatim from CLAUDE.md original lines 11453-11545 (M4.6 CLAUDE Context Normalization) -->
## Agent-Profile Track-Record Scoring: `producing_agent_profile` + `agent_profile_track_record.py` (2026-09-07)

Nothing in this repo recorded WHICH `.claude/agents/*.md` profile produced a given memory
record, and nothing joined that attribution against the real, already-existing
confirm()/retract() track-record mechanism `memory.py`'s `MemoryGC` already maintains --
confirmed by direct reading of `memory.py` and `confidence_calibration.py` before any edit
was made. `confidence_calibration.classify_record_outcome()` already answers, generically,
"what really happened to this record" (VERIFIED/REJECTED/INDETERMINATE, REJECTION checked
first so a confirmed-then-retracted record still counts as REJECTED); it groups outcomes by
CONFIDENCE TIER, never by which agent profile produced the record.

**`memory.py`: one new, purely additive field.** `MemoryStore.add()` gained
`producing_agent_profile`, defaulted via `mem.setdefault(..., None)` -- the identical
pattern `applicability_context` already established. A record whose writer never supplies
one (every real record on disk before this change, and every writer this pass did not
touch) is byte-for-byte unaffected: read back, it is `None`, indistinguishable from a
record file that predates this field entirely.

**`engine.py`: threaded, never re-derived.** `run_stage()` already resolves and attributes
a per-stage agent name at `_resolved_agent_name` (`route_info["agent"]`, the same value its
own stage-profiler `add_agent_run()` call already attributes runtime to). Each of the five
real memory-writing methods on a PASS/FAIL verdict --
`_promote_experience_knowledge`/`_promote_project_topology_knowledge`/
`_promote_vplan_summary_knowledge`/`_promote_verified_fix_knowledge`/
`_record_debug_attempt_job_memory` -- gained one new, optional, keyword-only-by-default
`producing_agent_profile` parameter, and their five real call sites now pass that same
`_resolved_agent_name` through, unmodified. No new resolution logic; no existing
positional/keyword call site (in production code or in the test suite) was touched.

**`dv_harness/agent_profile_track_record.py`: the read-only report, and only a report.**
`collect_agent_profile_track_record(root)` reads a project's real `MemoryStore` via
`store.find()` (never a write), buckets every real record by its
`producing_agent_profile` (a project with no memory store on disk reports `NOT_AVAILABLE`
WITHOUT ever constructing one -- the same "reading must never mint the store it asks
about" discipline `confidence_calibration.calibrate()` already enforces), and reuses
`confidence_calibration.classify_record_outcome()` VERBATIM for each record's real outcome
-- there remains exactly one definition of "what really happened to this record" in this
codebase. `env_manifest.build_generation_agent()` is reused, unmodified, to check whether
a named profile resolves to a real `.claude/agents/*.md` file (AGENT_PROFILE/SKILL/
NOT_FOUND/PROFILE_TREE_NOT_AVAILABLE) -- a fabricated profile name is reported `NOT_FOUND`,
never silently accepted as real. A record with no attribution at all is bucketed under a
distinct `UNATTRIBUTED` label, never folded into a named profile's own track record. Three
honest statuses: `NOT_AVAILABLE` (no store), `NO_ATTRIBUTED_RECORDS` (records exist, none
carry the field), `REPORTED` (at least one does). `memory.py` cannot import
`confidence_calibration.py` (that module already imports FROM `memory.py` -- a circular
import), which is the real, structural reason the read-side lives in this third module
rather than being folded into `memory.py` itself.

**Reporting only, and this is deliberate.** Nothing in this module, and nothing changed in
`engine.py`'s own dispatch, ever CONSUMES this field to alter routing, scoring, or
promotion. Per the Evidence Truth Rule, a finding this report surfaces (e.g. "one profile's
records get retracted far more often than another's") must never be applied directly to
production behavior -- acting on it would need a separate, human-approved change routed
through `capability_evolution.py`'s existing controlled-experiment machinery, exactly like
every other production-behavior change in this project. There is no `dv-harness` CLI verb;
the front door is the standalone `python -m dv_harness.agent_profile_track_record
{report|show}`.

Proven by `dv_harness_tests/test_agent_profile_track_record.py` (21 tests): backward
compatibility for every existing caller (the field defaults to `None`, matching a record
file that predates it); a real end-to-end `DVHarness.run_stage()` RE_AUDIT PASS over the
real shipped graph proving `engine.py` genuinely stamps its own resolved agent
(`review-agent`, RE_AUDIT's real declared graph agent) onto the `verified_fix` record it
writes, and that this module correctly reports and resolves it as a real `AGENT_PROFILE`;
the reused-outcome-classification proof via the identical confirmed-then-retracted case
`confidence_calibration.py`'s own suite uses; the three honest statuses including the
required negative control that a bare project is never minted a store merely by being
asked; a fabricated profile name resolving `NOT_FOUND`; the vocabulary-collision guard's
real detection power (monkeypatch-proven); an AST-based proof this module calls no
mutating `MemoryStore`/`MemoryGC` method; and a byte-identical-before-and-after proof that
reading the report never mutates an existing record.

**Baseline discipline (per this batch's own mandatory rule for a core-reasoning-engine
file).** Before any edit: the memory.py-focused suite (ten `test_memory_*.py` files plus
`test_confidence_calibration.py`/`test_cross_project_mining.py`/
`test_engineering_confirmation_accumulation.py`/`test_user_correction_trigger.py`/
`test_organizational_promotion_evaluation_wiring.py`) ran 356 passed, 1 pre-existing,
environment-dependent failure (`test_memory_vault.py`'s real obsidian-cli detection probe,
unrelated to memory content); `dv_harness_tests/test_engine_gates_and_routing.py` (engine.py's
own full suite) ran 238 passed, 1 pre-existing failure
(`test_verification_architecture_requires_fabric_topology_completeness_gate`, a documented,
already-disclosed `gates.py` registration gap unrelated to memory writing). After the
change: the identical suites plus the 21 new tests ran 377 passed / 238 passed, the SAME
single pre-existing failure each time, byte-identical otherwise -- zero regression. A
full-repo `pytest --collect-only` (13303 tests, zero collection errors) confirms no
import-time collision was introduced elsewhere in the suite.

**Disclosed residual.** This is REACHED, not WIRED into any decision: `producing_agent_
profile` is attributed only by the five real engine.py writers this pass touched (every
other real or future memory-writing call site starts this field at `None` until it is
similarly updated), and the report is a standalone Python/CLI artifact with no dashboard
card, stage gate, or `gates.py`/`cli.py` entry.


<!-- S203: moved verbatim from CLAUDE.md original lines 11546-11563 (M4.6 CLAUDE Context Normalization) -->
## Memory Retrieval: Usefulness-Weighted Ranking Mode (2026-09-07)

`MemoryRetriever.search()`'s existing fixed-heuristic score (relevance floor + confidence bonus + recency decay, see finding I2 above) is untouched and remains the DEFAULT for every existing caller. This item adds a second, purely opt-in ranking mode that folds this project's own real, already-recorded reuse signal -- `MemoryStore.mark_used()`'s `reuse_count`/`last_used_at` fields, which every existing writer has updated all along but which `search()` itself never read for ranking before this change -- into the score, without altering what the default path returns.

**REUSE, not reinvent.** No new signal, no new store, no new field: `reuse_count` was already persisted in every index row (`MemoryStore._index_row()`) and already incremented on every real `mark_used()` call. This change only teaches `search()` to optionally read it.

**Opt-in, additive, never applied to production scoring by default.** `MemoryRetriever.search(query, limit, now, rank_by=MemoryRetriever.RELEVANCE_RANK, usefulness_weight=1.0)` gained two new keyword-only parameters. `rank_by` defaults to `RELEVANCE_RANK` -- byte-for-byte the pre-existing formula, proven by a dedicated test comparing an omitted-argument call against an explicit `rank_by=RELEVANCE_RANK` call. Passing `rank_by=MemoryRetriever.USEFULNESS_RANK` adds `usefulness_weight * math.log1p(reuse_count)` on top of the existing score for every record that has already cleared the pre-existing relevance floor -- `log1p` so an unboundedly-reused record cannot dwarf the existing relevance/confidence/recency terms, and so `reuse_count == 0` (a never-reused record, or one whose field is simply absent) contributes exactly zero. The relevance floor itself (finding I2: a record with zero query overlap must never be returned purely from age/confidence) is completely unmodified and applies identically under both modes -- usefulness ranking only re-orders among records that already matched, it can never manufacture a match on reuse alone (proven by a dedicated negative-control test: 100 real `mark_used()` calls on a record with zero protocol/text overlap with the query still return `[]` under both ranking modes).

Per the Evidence Truth Rule, this is deliberately NOT a weight/threshold change applied directly to the production default -- it is a new, additive, explicitly-requested alternative a caller must opt into by name, so it needed no `capability_evolution.py` controlled-experiment routing. `usefulness_weight`'s default (1.0) only ever applies inside the new opt-in mode.

Reachable today as an explicit alternative via both `python -m dv_harness.memory_cli search --rank-by usefulness [--usefulness-weight N]` and `dv-harness memory-store search --rank-by usefulness [--usefulness-weight N]` (small, additive argparse/dispatch edits mirroring each script's own existing `--level`/`--confidence`/`--property` flags).

Proven by `dv_harness_tests/test_memory_usefulness_ranking.py` (8 tests, real `MemoryStore`/`MemoryStore.mark_used()` on disk, no mocking): the default-path byte-identity proof (omitted `rank_by` vs. explicit `RELEVANCE_RANK` produce identical scores regardless of real recorded reuse disparity); usefulness ranking promoting a more-reused record among otherwise-tied hits; a never-reused record scoring identically under both modes (the `log1p(0)==0` guarantee); a tunable-weight scaling proof driven through the real `mark_used()` mutator; the required negative control that heavy real reuse can never manufacture relevance on its own; an unrecognized `rank_by` value being rejected; and usefulness ranking still honoring every pre-existing structural filter (level/confidence/status/property).

**Disclosed side effect caught and fixed during this change**: adding these lines to `memory.py` shifted subsequent line numbers, which `dv_harness_tests/test_doc_citation_check.py` (a real, symbol-anchored citation-drift checker over `docs/MEMORY_ARCHITECTURE.md`/`docs/MEMORY_SCHEMA.md`) correctly caught as drift in 3 existing `file:line` citations. Fixed by updating those 3 citations to their real, current lines (`OrganizationalMemoryStore.add` -> `memory.py:1117-1149`, `_apply_confirmation_integrity` -> `memory.py:210`, `CornerCaseLibrary.add` -> `memory.py:910`); re-verified clean via `python -m dv_harness.doc_citation_check --memory-docs` (8/8 OK).

**Deliberately bounded**: this closes only the ranking-mode gap. It adds no new memory tier, no new admission gate, and no new persisted field -- `reuse_count`/`last_used_at` were already real and already written by every existing caller of `MemoryStore.mark_used()`. There is no automatic trigger switching a caller from `RELEVANCE_RANK` to `USEFULNESS_RANK` -- every existing production call site (`engine.py`, `cli.py`'s other memory-related verbs, `memory_vault.py`'s separate Markdown-note search) is unaffected and continues to use the unchanged default.


<!-- S206: moved verbatim from CLAUDE.md original lines 11586-11685 (M4.6 CLAUDE Context Normalization) -->
## Skill-Routing Accuracy Tracking: an Additive Decision/Outcome Recorder Over router.py (2026-09-07)

`router.py`'s `RouteResolver.resolve()` and `protocol_router.resolve_protocol()` are pure functions --
each computes an answer and hands it to its caller, and nothing anywhere kept a real, persisted record
of what either one decided, or joined that decision against what actually happened next. Confirmed by
direct reading before writing anything: no code path in this repository wrote a routing decision to
`.dv-harness/events.jsonl`, so a real question this project's own evidence trail could in principle
answer -- "when this stage's skill/agent routing resolved a particular way, did the stage go on to fail
for a reason a missing or wrong-routed skill would explain" -- had no real data behind it at all.

`record_routing_decision()`/`record_routing_outcome()`/`skill_routing_accuracy_report()` close that
gap, added strictly ADDITIVELY at the end of `router.py`. `resolve()`, `resolve_protocol()`,
`resolve_intent()`, `research_route_plan()`, `RouteResolver` and `DEFAULT_ROUTES` are byte-for-byte
untouched -- no existing function's signature, return value, or behavior is read, mutated, or in any
way affected by anything below, and no weight/threshold/routing-decision logic was added: nothing here
writes to `DEFAULT_ROUTES`/`PROTOCOL_SENSITIVE_SKILLS` or any other value `resolve()`/`resolve_protocol()`
actually reads. Per this project's own governing rule, any real routing-BEHAVIOR change (e.g.
auto-preferring one route over another based on a finding this mechanism surfaces) would itself be a
production-behavior change and would have to be proposed as data through `capability_evolution.py`'s
existing controlled-experiment machinery for a human to approve -- nothing here does that, or could.

**REUSE OVER REINVENT, on every mechanism this needed.** Persistence is the SAME real
`storage.StateStore.event()` every other subsystem in this harness already writes
`.dv-harness/events.jsonl` through -- `loop_telemetry.py`, `live_event_model.py`, `gui_audit_log.py` --
there is no second event file and no second serializer here. `record_routing_decision(store, decision,
*, kind, stage=, run_id=, source=)` persists the ALREADY-COMPUTED real return value of
`RouteResolver.resolve()` (`kind=ROUTING_DECISION_KIND_ROUTE`) or `protocol_router.resolve_protocol()`
(`kind=ROUTING_DECISION_KIND_PROTOCOL`) -- it never calls, re-derives, or second-guesses either
function, only records the answer they already gave, and returns the full record including a real,
process-unique `decision_id` (timestamp + pid + a monotonic per-process counter, closing the theoretical
same-microsecond-collision edge case `loop_telemetry.new_run_id()`'s own coarser second-resolution
stamp merely accepts). `skill_routing_accuracy_report()` reuses `loop_telemetry.read_events()` -- that
module's own public, generic events.jsonl reader, already the reuse target `platform_health.py`/
`live_event_model.py` both point at -- rather than a third independent parser.

**The outcome-classification vocabulary is grounded, never invented.**
`record_routing_outcome(store, decision_id, gate_reasons=, ...)` records a LATER real outcome joined by
the decision's own `decision_id`, classified by `classify_routing_outcome()` -- a LITERAL match (never a
semantic reading of gate text) against a small, closed, cited set of real sentinels this harness's own
routing/dispatch machinery already writes today: `protocol_router.resolve_protocol()`'s own real
`"UNRESOLVED_NEEDS_ROUTING_QUESTION"` reason string (this very module's own sibling function, defined
above), `tools/verification_flow/protocol_profile_binding_gate.py`'s own real `gate_id`
(`"protocol_profile_binding_gate"`, registered in `gates.STAGE_GATES["PROTOCOL_CAPABILITY"]` -- that
gate exists precisely to check whether a protocol's resolved profile/vip-lookup skill was actually
consulted, per this file's own NOTICE at the top) together with its own literal
`"PROFILE_SKILL_NOT_CONSULTED"` FAIL reason, and `agent_dispatch.py`'s own real `NOT_DISPATCHED` status
literal. Requiring BOTH the gate id AND its own reason (never either alone) is a deliberate,
tested guard against a false match on a gate's own id appearing in an unrelated, passing reason.

**Evidence Truth Rule, applied to every honest-absence case a caller could hit.** An empty/absent
`gate_reasons` list is `OUTCOME_NO_OUTCOME_YET` -- "no outcome has been observed yet" is a different
fact from "checked and found nothing routing-related", and the two are never conflated. A real gate
failure whose text matches none of the three cited sentinels is honestly
`OUTCOME_NOT_EXPLAINED_BY_ROUTING` -- never silently folded into "routing was fine". A project on which
neither recording function has ever been called reports `{"available": False, "reason":
NO_ROUTING_DECISIONS_RECORDED, ...}` and mints no `.dv-harness/` tree merely by being asked -- a REACHED
capability (a real Python API a caller invokes directly), not a WIRED one: nothing in
`engine.run_stage()` calls either recording function today, so this must never present a bare project's
own real absence of records as a fabricated clean report. `explains_failure_rate` is computed ONLY over
decisions carrying a real observed outcome (never `NO_OUTCOME_YET` decisions), and is honestly `None`
with a stated reason rather than a fabricated number over a zero denominator; a decision re-observed
more than once uses only its LATEST recorded outcome, since a later real observation supersedes an
earlier one.

**Deliberately bounded, and stated rather than implied closed.** It records and reports only -- no gate
is invoked, no build/regression/LSF job is touched, no approval is minted, and there is deliberately no
stage gate of its own. It never picks a route, never overrides a route, and never decides which of two
recorded outcomes is "correct" -- a real `OUTCOME_NOT_EXPLAINED_BY_ROUTING` finding is reported for a
human/future integration to act on, never resolved by this mechanism. There is no `dv-harness` CLI verb
and `engine.py`/`gates.py`/`cli.py` were not touched -- the front door is the module's own Python API
(`router.record_routing_decision`/`router.record_routing_outcome`/`router.skill_routing_accuracy_report`),
matching this project's own established convention for a small, standalone additive capability. Wiring
either recording function into `engine.run_stage()`'s real dispatch path (so every real `RouteResolver.
resolve()` call and its stage's own real gate outcome get recorded automatically) is a separate,
disclosed follow-up this pass does not attempt.

Proven by `dv_harness_tests/test_router_skill_routing_accuracy_tracking.py` (28 tests,
`python -m pytest dv_harness_tests/test_router_skill_routing_accuracy_tracking.py -q` -> `28 passed`):
three mutation-style tests proving the two import-time vocabulary/collision guards have real detection
power (via `monkeypatch`, not merely never firing); `classify_routing_outcome()` driven against a REAL
`resolve_protocol()` unresolved result and against the EXACT real `f"{gate_id}: {gr.detail}"` string
shape `gates._evaluate_stage_evidence_core()` actually builds for a failing gate, for all three grounded
signals plus the required negative controls (empty `gate_reasons` -> `NO_OUTCOME_YET`; a real-but-
unrelated gate failure, and the gate-id-alone/reason-text-alone near-miss cases, -> honestly
`OUTCOME_NOT_EXPLAINED_BY_ROUTING`, never a false positive); `record_routing_decision()`/
`record_routing_outcome()` round-tripped through a real `storage.StateStore`/`.dv-harness/events.jsonl`,
including four refusal negative controls (an unrecognized `kind`, a non-dict decision, a non-JSON-
serializable decision, a blank `decision_id`) each proven to write NOTHING to disk; a dedicated test
proving `RouteResolver.resolve()` called before and after `record_routing_decision()` returns
byte-identical output; and `skill_routing_accuracy_report()` proven against a real multi-decision/
multi-outcome scenario (including a stale-outcome-superseded-by-a-later-real-one case and a reuse proof
that monkeypatching `loop_telemetry.read_events` changes what the report sees). Baseline/regression:
router.py's own complete real pre-existing test suite -- `dv_harness_tests/test_route_resolver_protocol_
fold_in.py`, `dv_harness_tests/test_research_intent_routing.py`, `dv_harness_tests/
test_model_agent_tool_router.py`, `dv_harness_tests/test_protocol_and_environment_mode_engine_wiring.py`,
`dv_harness_tests/test_agent_dispatch_map.py` -- was run green BEFORE this change and re-run green AFTER
it (165+17 = 182 tests total across the router-touching suites, zero failures either time), and a
full-repo `pytest --collect-only -q` collected all 13499 tests with zero collection errors, confirming
no import-time regression was introduced anywhere in the codebase.


<!-- S207: moved verbatim from CLAUDE.md original lines 11686-11766 (M4.6 CLAUDE Context Normalization) -->
## Adaptive ReAct Iteration Budget: Complexity-Sensitive, Opt-In (2026-09-07)

`react_loop.py`'s `InnerReactLoop.run()` previously read its two safety-backstop numbers --
`policy.inner_react_max_iterations`/`policy.inner_react_max_adapter_calls` -- as two fixed
constants (default 3, 2) via a plain `policy.get(key, default)`. Nothing scaled that budget to
how complex the current investigation actually is. `dv_harness/react_loop.py` gained a new,
OPT-IN policy mode -- `compute_adaptive_react_budget(cfg, root)` -- that can scale both numbers
with a real, mechanically-computed complexity signal instead: the number of distinct files
`git diff --name-only HEAD` shows as touched in the current worktree, and the number of distinct
top-level subsystem directories those files sit under (`_distinct_subsystems()`), mirroring
`engine.DVHarness._git_modified_files()`'s own real-evidence convention (re-derived locally, not
imported, so `react_loop.py` stays importable/testable standalone without an
`engine.DVHarness` instance -- the same reasoning this module's own "SECOND DEVIATION" note
already gives for threading `profiler`/`profile_id`/`agent_name` through as plain parameters).

**Default behavior is byte-identical for every project that has not opted in.** A new
`config.DEFAULT_CONFIG` sub-block, `policy.adaptive_react_budget`, defaults to
`{"enabled": False, "min_iterations": 2, "max_iterations": 6, "files_per_iteration_step": 3,
"min_adapter_calls": 1, "max_adapter_calls": 4, "subsystems_per_iteration_step": 1}` -- the same
explicit opt-in convention every other production-behavior flag in `DEFAULT_CONFIG` already uses
(`self_tuning.enabled`, `escalation.enabled`, `dry_run.enabled`). With it absent or `False`,
`compute_adaptive_react_budget()` falls straight back to the EXACT SAME two
`policy.get("inner_react_max_iterations", 3)` / `policy.get("inner_react_max_adapter_calls", 2)`
reads `InnerReactLoop.run()` used before this change, and never invokes a git subprocess at all
-- proven directly by a test that monkeypatches `subprocess.check_output` to raise in that
branch. `InnerReactLoop.__init__()`/`.run()` keep their exact existing signatures; `engine.py`'s
one real call site (its `InnerReactLoop(...).run(...)` inside `run_stage()`) needed no change and
was verified unaffected. `InnerReactOutcome` gained one new, optional `budget_info` field
(default `None`) purely for observability.

**Opt-in, clamped, never unbounded.** With `adaptive_react_budget.enabled=true`, each budget
scales linearly from its declared floor and is clamped at its declared ceiling:
`max_iterations = clamp(min_iterations + floor(distinct_file_count / files_per_iteration_step),
min_iterations, max_iterations)`, and the symmetric formula for `max_adapter_calls` over
`distinct_subsystem_count`/`subsystems_per_iteration_step`. Every one of those six numbers is a
human-editable `config.json` field this function reads, never a hidden constant. No real git
evidence (no repo, or nothing modified) floors both budgets at their declared minimums -- never
crashes, and never reads absence of evidence as "unlimited complexity". A malformed
`adaptive_react_budget` block (a non-numeric field, an inverted min/max) is caught and degrades
to the same safe fixed-mode result, mirroring this module's own established
"observability/an opt-in mode must never break an already-computed verdict" discipline (see
`react_recorder.record_reflection()`'s own try/except one function above).

**Per this project's own rule that a weight/threshold change must never be silently applied to
production scoring**: this mode is completely dormant until a human explicitly flips
`adaptive_react_budget.enabled` on in a project's own `.dv-harness/config.json` -- no code path in
this harness ever sets it. This is a declared, human-owned config toggle, not an auto-tuned
production behavior change routed through `capability_evolution.py`'s controlled-experiment
machinery (that machinery is for a proposed CHANGE TO THE DEFAULT itself; this is an explicit,
opt-in ALTERNATIVE MODE a project chooses for itself, the identical shape every other
`DEFAULT_CONFIG` opt-in flag already has).

**Deliberately bounded, and stated rather than implied closed.** (1) "Subsystem" here is
deliberately a coarse, purely structural grouping -- the distinct top-level path segment of each
real git-modified file -- never a semantic DV protocol/subsystem classification (that stays
`protocol_router.py`'s/`environment_mode_router.py`'s own, separate job); it exists only to size a
retry/iteration budget. (2) The complexity signal is `git diff --name-only HEAD` against the
current worktree at the moment `InnerReactLoop.run()` is called -- a snapshot, not a
per-stage-attempt delta; a project with no git repo at all (or one whose complexity does not show
up as a file diff) simply floors at the declared minimums, honestly. (3) No `dv-harness` CLI verb
or `gates.py` entry was added or needed -- the mode is read purely from `config.json` at the one
real call site inside `InnerReactLoop.run()`.

Proven by 11 new tests in `dv_harness_tests/test_react_loop.py`: the default-disabled path proven
byte-identical to the old two-`.get()` reads (with a monkeypatch proving git is never invoked in
that branch); empty/`None` cfg; `enabled: False` never leaking its own declared fields into the
fixed result; the required negative control that an absent real git repo floors both budgets at
their declared minimums rather than crashing or reading absence as unlimited complexity; a real,
throwaway git repository (the same `git init`/`config`/`add`/`commit` fixture convention
`test_safety_sandbox.py`'s own `_init_repo()`/`git_repo` fixture already establishes) proving the
scaled formula against hand-computed expected values, and a larger real investigation proving the
clamp at the declared ceiling; a malformed config field falling back to fixed mode rather than
raising; and two `InnerReactLoop.run()` integration tests proving the computed budget genuinely
GOVERNS the real loop -- a small real investigation scales `max_adapter_calls` down to one fewer
than the real `_TwoStepRetryAdapter` fixture needs, and the loop provably stops one call short of
PASS; a larger real investigation scales the same budget up enough, and the identical
adapter/gate fixture reaches real PASS in exactly the same call count the pre-existing
fixed-budget test already established. The full, current `dv_harness_tests/test_react_loop.py`
suite (32 tests: every pre-existing test in the file plus these 11) passes together in one
consolidated run.


<!-- S208: moved verbatim from CLAUDE.md original lines 11767-11783 (M4.6 CLAUDE Context Normalization) -->
## Automatic Reevaluation of Prior Capability-Evolution Decisions (2026-09-06, Research-Capability Evolution master prompt section 77)

**Gap.** CLAUDE.md's own "Cross-Loop Coupling" section above documents, correctly, that a candidate a human has already moved off DISCOVERED is "never dragged back" -- `file_repeated_failure_candidate()` reports `ALREADY_BEYOND_DISCOVERED` and writes nothing once that has happened. That refusal is right and stays untouched. But it leaves a real, named gap: once a candidate reaches REJECTED, or a human records `final_decision: "HOLD"`, `ALREADY_BEYOND_DISCOVERED` is the LAST thing anyone ever hears about it -- even if the exact same root cause goes on to recur across several more independent runs, or a second and third project's memory store independently confirms it. Nothing in this codebase ever told a human "the evidence behind a decision you already made has grown since you made it." A repo-wide grep (2026-09-06) for `reconsider`/`re-evaluat` across `dv_harness/` found nothing.

**What's new -- `dv_harness/prior_decision_reevaluation.py`.** Detection-only, exactly as the task specifies: it never calls `capability_evolution.transition()`, never edits `current_status`/`promotion_status`/`final_decision` on the candidate it examines, and never files a new candidate -- only ever ONE flagged-reconsideration record, written to Working Memory under its own `capability_decision_reconsideration_flag` kind (distinct from `CANDIDATE_MEMORY_KIND` so a flag is never mistaken for a candidate).

- `prior_decision_status(candidate)` classifies a persisted candidate's OWN already-recorded fields into REJECTED / HOLD / SUPERSEDED / `NOT_A_PRIOR_DECISION`, never free text. REJECTED reads `current_status`/`promotion_status` (`capability_evolution.PROMOTION_STATES`' own terminal state) and its real `decided_at` off the matching `status_history` entry. HOLD reads the schema's own `final_decision` field -- real, but with no producer anywhere in this codebase beyond `build_candidate()`'s `PENDING` default, so its `decided_at` is honestly `None` rather than fabricated. SUPERSEDED is the interesting honesty case: that token exists NOWHERE in `capability_evolution.PROMOTION_STATES` or the candidate schema's `final_decision` enum (checked by grep before this module was written), and the one real SUPERSEDES-shaped precedent in this codebase -- `doc_extraction.prior_research_relations()` -- is a relation `capability_evolution.py` itself deliberately NEVER DERIVES ("a comparator that guessed them would fabricate exactly the kind of agreement section 28 warns about"). This module follows the identical discipline one level over: `prior_decision_status()` reports SUPERSEDED ONLY when the candidate already carries a caller-declared `superseded_by` reference, and never guesses it from absence.
- `detect_new_repeated_failure_evidence()` re-runs the REAL, unmodified `capability_evolution.repeated_unresolved_failure_patterns()` and compares its current `memory_ids` for the candidate's own cited signature (read only from `trigger_source`'s real `job_memory:failure_signature:<key>` value -- never guessed from hypothesis prose) against the candidate's own `evidence_refs` at decision time. A strict superset is new evidence; an unchanged or now-empty set (the pattern closed by a real `verified_fix`) is honestly nothing.
- `detect_new_cross_project_evidence()` takes the CALLER's own already-computed `cross_project_mining.mine_cross_project_patterns(...)["cross_project_patterns"]` list -- this module mines no cross-project store and registers no project itself, since that machinery is `cross_project_mining.py`'s end to end -- and applies the identical superset comparison across every contributing project's `memory_ids`.
- `detect_reconsiderations()` composes the two, restricted to candidates `prior_decision_status()` actually classifies as REJECTED/HOLD/SUPERSEDED; a live DISCOVERED/PENDING candidate is never examined even when new evidence exists for its own signature. `file_reconsiderations()` persists through the same `memory_router.route_and_store()` `capability_evolution.persist_candidate()` uses, asserting the WORKING_MEMORY destination the same way, and is idempotent -- a content-derived `RCF-<hash>` flag_id (minted exactly like `mint_candidate_id()`) means re-detecting identical evidence reports `ALREADY_FLAGGED_UNCHANGED` rather than duplicating a Working Memory record.

**Reused, not reinvented.** `capability_evolution.repeated_unresolved_failure_patterns()`, `read_candidates()`/`read_candidate()`, `cross_project_mining.mine_cross_project_patterns()`, and `memory_router.route_and_store()`/`memory.MemoryStore.find()` are all imported unchanged; this module adds no second definition of "the same failure," "closed," or "independent." `capability_evolution.py` (3000+ lines) and `cross_project_mining.py` were left untouched, per this task's own file-safety scope, in favor of a standalone front door: `python -m dv_harness.prior_decision_reevaluation {detect|file} --root <root> [--candidates <file.json>] [--cross-project-patterns <file.json>]`. No `dv-harness` CLI verb was added and `cli.py`/`gates.py` were not touched.

**Deliberately bounded, disclosed.** No cross-project mining runs on its own -- a caller must already have registered its own projects and run `mine_cross_project_patterns()`. A human-authored candidate naming no `job_memory:failure_signature:` `trigger_source` is never matched to any pattern (repeated-failure or cross-project) by this module, since doing so would mean inferring a failure signature from free-text hypothesis prose -- exactly the kind of guess the Evidence Truth Rule forbids. And this module reverses nothing: a flagged record's own `recommended_action` text states that reversal is a separate human-authored `transition()` call, never an automatic consequence of a flag.

Proven by `dv_harness_tests/test_prior_decision_reevaluation.py` (19 tests, `python -m pytest dv_harness_tests/test_prior_decision_reevaluation.py -q` -> `19 passed`), all against real stores: status classification for all four outcomes including the negative "no declaration is never guessed SUPERSEDED"; the headline negative controls this task is graded on -- a REJECTED decision with unchanged evidence flags nothing, a pattern CLOSED by a real `verified_fix` after rejection is never misread as growth, and a still-live DISCOVERED candidate is never examined even with new matching evidence; a new independent job-failure run after rejection IS detected, with the exact new `memory_id` named; cross-project detection over two real project memory stores via a real `mine_cross_project_patterns()` call; filing to Working Memory, idempotent re-filing, and proof the flagged candidate's own `current_status`/`final_decision` is byte-for-byte unchanged after filing; flag_id stability/content-derivation; and the CLI front door end to end.


<!-- S222: moved verbatim from CLAUDE.md original lines 12480-12564 (M4.6 CLAUDE Context Normalization) -->
## Memory Quality / Forgetting: the DECISION Policy Over MemoryGC's Own Mechanism (2026-09-06, targeted_hardening item `memory_quality_forgetting`, spec section 228)

Confirmed by direct search before writing a line of this module: `dv_harness/memory.py`'s `MemoryGC`
already has the real, tested MECHANISM for demoting/retiring a record -- `flag_stale()` ("needing
revalidation ... it has aged past `knowledge_center.max_age_days`"), `deprecate()` ("retired, not
refuted") and `supersede()` ("a newer, corrected record replaces this one") -- but nothing anywhere
called any of them from an automatic age/never-confirmed/duplicate DECISION.
`self_learning_readiness.py`'s own `revalidation_queue` row only READS records `MemoryGC.
flag_stale()` has *already* marked `NEEDS_REVALIDATION`; nothing produced that mark in the first
place. `user_correction_trigger.py` is the nearest-looking module and is genuinely a different
mechanism: it reads `RETRACTED`/`SUPERSEDED` records a HUMAN correction already produced, to detect a
repeated-mistake pattern for capability evolution -- it never decides to retract/supersede/deprecate
anything itself.

`dv_harness/memory_quality_policy.py` is the missing DECISION layer those two read from. It looks at
a record's own real, already-recorded evidence (`created_at`, `last_confirmed_at`, `last_used_at`,
`confirmation_count`, `reuse_count`, `status`) and a structural duplicate check, and recommends -- or,
opted in, actually applies -- exactly the `MemoryGC` call that evidence supports. No new persistence
mechanism was built, and `memory.py` was not edited: the module is a pure caller of the existing,
unmodified `MemoryGC`/`MemoryStore` API.

**Three retirement grounds, exactly the item's own three, never a fourth.** (1) **Age** -- a record
nobody has touched (confirmed, reused, or even created) inside `stale_after_days` is demoted to
`NEEDS_REVALIDATION` (`MemoryGC.flag_stale()`). This alone never retires it outright: `MemoryGC.
confirm()` restores it to `ACTIVE` the moment a fresh independent confirmation arrives, exactly as
that method's own docstring already promises. (2) **Never-confirmed** -- a record that has gone
`deprecate_after_days` (deliberately DOUBLE the staleness window, so the two thresholds can never
silently drift apart) with `confirmation_count == 0` AND `reuse_count == 0` is retired outright
(`MemoryGC.deprecate()`). A record anyone has ever reused or independently re-derived never qualifies
for this ground however old it is; age alone routes it through ground 1 instead. (3) **Superseded** --
two or more `ACTIVE` Engineering-tier records sharing the identical `(protocol, root_cause)` pair are
a genuine STRUCTURAL duplicate, using the exact same "same finding" equality
`memory.find_confirming_engineering_match()` already applies at write time (case-insensitive on
`root_cause`, exact on `protocol`) -- reused here, never re-derived. The strongest surviving record
(highest `confirmation_count`, then most recent `created_at`, then `memory_id` for a fully
deterministic tie-break) is kept `ACTIVE`; every other member of the group is superseded by it
(`MemoryGC.supersede()`), citing the real winner `memory_id`. Deliberately scoped to
`engineering`-tier records only, for the identical reason `find_confirming_engineering_match()` is
itself scoped there.

**Evidence Truth Rule, enforced rather than merely stated.** A record carrying no `created_at` at all
has no age evidence and is recommended `NONE` naming `NO_AGE_EVIDENCE`, exactly the same "we could
not check" honesty every other module in this codebase applies to a missing fact. A record already
`DEPRECATED`/`RETRACTED`/`SUPERSEDED` is left alone (`STATUS_ALREADY_TERMINAL`) -- this policy never
re-retires an already-retired record, and never overwrites a human's own retraction/supersede reason
with a policy-generated one. `evaluate_memory_quality()` (the report/dry-run half) checks
`cross_project_mining.has_memory_store()` BEFORE ever constructing a `MemoryStore` (whose constructor
unconditionally `mkdir()`s the tree and writes an empty `index.json`), so a project that has never
used its memory store gains one merely by being asked whether its memory quality needs attention --
it reports `NOT_AVAILABLE` instead. `apply_memory_quality_policy()` calls the same evaluation and
then, only when `dry_run=False`, calls the real `MemoryGC` methods the evaluation already named --
there is no second, parallel writer. Declared policy thresholds are read directly from
`.dv-harness/config.json` via a plain `json.loads()` (never `config.load_config()`, which would
materialize a default config.json for a project that has none). An absent or non-declaring config
reports the honest built-in default, `DEFAULT_STALE_AFTER_DAYS` (180 days -- the SAME number this
file's own Engineering Memory Policy already documents for `knowledge_center.max_age_days`'s
identical concept on the shared Knowledge Center side, reused here for the local store that
mechanism does not itself cover).

Front door: `dv-harness memory-quality-policy report|apply [--stale-after-days N]
[--deprecate-after-days N] [--json]`, and the identical `python -m dv_harness.memory_quality_policy`
(one shared `execute_verb()`). It decides, approves and arbitrates nothing beyond calling the
pre-existing `MemoryGC` mechanism: no build, job, or approval is touched, and there is deliberately
no stage gate -- a gate that silently retired a record nobody reviewed would be worse than none.

**Disclosed residual**: this is REACHED, not WIRED. There is a real `dv-harness` CLI verb (unlike
several sibling same-day modules that skip CLI wiring entirely), but no `run_stage()`/`advance()`
call site invokes `evaluate_memory_quality()`/`apply_memory_quality_policy()` at any stage boundary,
and no graph node declares it -- a project's memory quality is only re-evaluated when a human or
script runs the verb, not automatically at a regression-cycle boundary the way `question_queue.py`'s
digest is (see "Question-Queue Digest: Auto-Fired at Regression-Cycle Boundaries" above for that
different mechanism's own stage-boundary wiring, which this module does not reuse or extend).

Proven by `dv_harness_tests/test_memory_quality_policy.py` (28 tests) against the REAL
`MemoryStore`/`MemoryGC` on a real temp directory -- no hand-written record files, no mocks of
either class. The negative controls are what give it detection power: a record with no age evidence,
or one already retired, is proven to never be silently fabricated a staleness/deprecation/duplicate
finding; a record genuinely re-confirmed through the real `MemoryGC.confirm()` resets the staleness
clock; ground 2 is proven to never fire when a record was ever reused OR ever confirmed however old
it is; the duplicate-detection ground is proven to never cross a tier boundary and to never fabricate
a match without a real `(protocol, root_cause)` pair; a dry-run report is proven byte-for-byte
non-mutating; and both the `report` and `apply` CLI verbs are driven as real subprocesses, including
the exit-2 `NOT_AVAILABLE` path on a bare root. `python -m pytest
dv_harness_tests/test_memory_quality_policy.py -q` -> `28 passed`.


<!-- S258: moved verbatim from CLAUDE.md original lines 15180-15269 (M4.6 CLAUDE Context Normalization) -->
## Checker / Scoreboard Qualification: a Real Track-Record Record, Distinct from Placement (2026-09-06)

Section 158 asks for a qualification record/gate over a checker or scoreboard's OWN
trustworthiness track record: has it ever caught a real injected defect, has it ever produced
a false PASS. Re-verified by direct search before building: `grep -rn "fault_injection\\|
checker_qualification\\|scoreboard_qualification\\|checker_trust\\|false_pass_history\\|
injected_defect\\|track_record" dv_harness/*.py`): zero hits. `verification_architecture.py`'s
`CheckerIR`/`ScoreboardIR` are explicitly PLACEMENT records (bind target, mount side relative
to a bridge, endpoint comparability) with no track-record concept, and `golden_scenario.py`'s
capsule store cannot even hold this evidence -- `validate_capsule()` REFUSES any capsule whose
`expected_result` is not itself a real PASS verdict, so a checker's FAIL-verdict "caught a
defect" evidence has structurally nowhere to live there.

`dv_harness/checker_sb_qualification.py` is that missing record and gate, and it respects the
honest boundary `subsystem_maturity_gate.py`'s own `false_pass_count_zero` condition already
states: that condition's `FALSE_PASS_SIGNAL_SEARCH_NOTE` records that, before this module,
neither `golden_scenario.py` nor `requirement_contract.py` (the two modules its own spec named
as the likeliest home) nor any other real producer persisted a false-PASS COUNT over a
qualification set, and that `tools/verification_flow/false_pass_resistance_gate.py` is a
per-stage, AGENT-ATTESTED evidence-block shape check (5 boolean claims), not a count.

**A `QualificationTrial` is one real, evidence-cited trial**: a known defect was deliberately
made present for one named checker/scoreboard `component_id`, and the component's own recorded
verdict for that specific trial decides the outcome -- `DETECTED` (a real FAIL), `FALSE_PASS`
(a real PASS despite the defect), or `INDETERMINATE` (no verdict recorded, or an unrecognized
one) -- DERIVED from the verdict, never asserted directly by a caller. Every trial construction
REFUSES (raises) without a non-empty `injection_evidence` citation, and refuses a declared
`component_verdict` with no `verdict_evidence` citation -- an uncited claim is exactly the
unsupported claim the Evidence Truth Rule forbids, enforced at the dataclass's own construction
boundary rather than left as prose, the same discipline `security_policy_ir.AccessRule` and
`arbitration_policy_ir.ControllingMechanism` already apply to their own domains.

**Worst-wins, never averaged, per this project's own composite-gate convention.**
`evaluate_component_qualification()` folds one component's whole trial history: a single
confirmed `FALSE_PASS` disqualifies the component (`DISQUALIFIED_FALSE_PASS_CONFIRMED`)
regardless of how many detections it also has on record -- a checker that mostly works and
once silently missed a real defect is not "mostly trustworthy," because the whole point of a
checker is that a human can stop looking once it says PASS. Only with zero false passes does
the detection count matter: `>= MIN_CONFIRMED_DETECTIONS` (2, the same "shown twice, not once"
floor `memory_router.ORGANIZATIONAL_MIN_CONFIRMATIONS`/`capability_evolution.
REPEAT_FAILURE_MIN_OCCURRENCES`/`STABILITY_WINDOW_MIN_RUNS` already use) is `QUALIFIED`, fewer
is `PARTIALLY_QUALIFIED`. A component with real trials on file but every one `INDETERMINATE` is
`EVIDENCE_INCONCLUSIVE`, kept honestly distinct from `no_trials_recorded()`'s
`NO_TRIALS_RECORDED` (never tried at all vs. tried and could not tell -- different operator
problems, different remedies). `evaluate_qualification_gate()` folds several components the
same worst-wins way into `QUALIFIED`/`NOT_QUALIFIED`/`INCOMPLETE_EVIDENCE`, and a caller-named
`required_components` list folds an unmentioned, unqualified component in as its own honest
`NO_TRIALS_RECORDED` record rather than letting it silently drop out of the gate.

Vocabulary (`TRIAL_OUTCOMES`/`QUALIFICATION_STATUSES`/`GATE_VERDICTS`) is asserted disjoint
from `dv_harness.models.Status` at import time, the same guard several sibling
domain-vocabulary modules already run against themselves. Rendering reuses
`connectivity.render_markdown_table()` -- this repo's one parameterized table renderer.

**What this module cannot do, stated up front.** It cannot inject a fault into a DUT/TB
itself -- this harness owns no RTL, no live simulator and no formal tool, the identical
boundary `mutation_testing.py`'s own docstring states for its own, unrelated,
Python-test-suite-scoped mutation engine ("DUT/RTL-level fault injection... needs a real RTL
target and a simulator this repository does not contain"). It cannot verify that a caller's
claimed injected defect was real or that a cited verdict is accurate -- the same TRUTH-versus-
PRESENCE limit `user_answer_validator.py` and `vip_api_card.py` already draw for a citation.
What it CAN do, and does, is refuse to accept a qualification claim with no real citation at
all, and derive an honest, worst-wins verdict from whatever real trials a caller supplies.

**Deliberately bounded, and stated rather than implied closed.** (1) It decides, approves and
arbitrates nothing beyond its own classification: no build, no job, no approval, and there is
deliberately no `STAGE_GATES` entry -- ad hoc front door is
`python -m dv_harness.checker_sb_qualification evaluate --trials <file.json> [--required
component_id:kind ...] [--json]` (exit 0 `QUALIFIED`, 1 `NOT_QUALIFIED`, 2
`INCOMPLETE_EVIDENCE`/usage error). No `dv-harness` CLI verb was added and `gates.py`/`cli.py`
were not touched, per this task's own file-safety scope. (2) It never imports or modifies
`verification_architecture.py`, `golden_scenario.py`, or `subsystem_maturity_gate.py` -- a
deliberate, disclosed choice. Building this module does NOT retroactively resolve
`subsystem_maturity_gate.py`'s own `false_pass_count_zero` condition: that condition is
UNTOUCHED here and, honestly, still reports `NOT_MEASURABLE` until a future change wires the
two together. What changes is that a checker/scoreboard's own qualification history now has
somewhere real to be recorded and queried for the first time.

Proven by `dv_harness_tests/test_checker_sb_qualification.py` (31 tests): trial construction
and outcome derivation (FAIL->DETECTED, PASS->FALSE_PASS, absent/unrecognized->INDETERMINATE);
the three citation-refusal negative controls (missing `injection_evidence`, missing
`verdict_evidence`, an invalid `component_kind`); the required negative control proving the
module refuses to fabricate a verdict when no trials exist
(`test_negative_control_no_trials_never_fabricates_a_verdict`); the worst-wins headline proof
(five clean detections plus one confirmed false PASS still disqualifies); the
all-indeterminate-vs-no-trials distinction; mismatched-component refusals; the project-wide
gate's worst-wins fold and its required-but-missing-component handling; the vocabulary-collision
guard with real detection power (a monkeypatch test proving it actually trips); and 5 CLI
subprocess tests exercising all three exit codes.


<!-- S268: moved verbatim from CLAUDE.md original lines 15843-15897 (M4.6 CLAUDE Context Normalization) -->
## Memory/Buffer Architecture Extraction: Depth/Width/Port-Role Facts, Confidence Kept Separate (2026-09-07)

Nothing in this repo interpreted a declared RTL array as a memory/FIFO/buffer structure before
this item: `env_manifest.py`'s `dut_facts.rtl` layer is a pure pass-through of `verible_parser.py`'s
already-flattened `rtl_modules`/`rtl_ports`/`rtl_signals`/`rtl_parameters` tables, with no depth/
width/port-role interpretation at all, and `design_architecture_ir.py`'s own "depth" hits are
unrelated instance-tree nesting depth, not a memory's storage depth (confirmed by grep before
writing a line of this module, per REUSE OVER REINVENT). `dv_harness/memory_buffer_arch_extraction.py`
closes that gap by sitting on top of the one real SystemVerilog front end both of those modules
already share (`verible_parser.parse_file()`/`extract_modules()`), never adding a second parser.

**What counts as a real structure, and only that.** A module-level signal declaration whose
`unpacked_dims` text is real and non-empty -- a register file's `logic [31:0] mem [0:DEPTH-1];`, a
FIFO's `logic [WIDTH-1:0] fifo_mem [0:DEPTH-1];` -- is the RTL evidence a storage array exists;
verible_parser.py's own docstring already names this exact shape as what its signal extraction is
built to surface. A module with no such signal has, at this parser's own declaration-level scope,
no memory/FIFO/buffer structure to report, and the module says so honestly (`NOT_AVAILABLE`)
rather than inferring one from a plausible module or port name.

**Three facts, three independent confidence levels, never blended.** DEPTH is parsed from the
array's own unpacked-dimension bracket range: two literal bounds resolve directly
(`DEPTH_RESOLVED_LITERAL`); a bound naming one of the module's OWN parameters resolves through
that parameter's declared default (`DEPTH_RESOLVED_VIA_PARAMETER` -- a caller-supplied override at
bind time is a different fact this parser cannot see and this module never invents); anything
outside that bounded grammar is `DEPTH_SYMBOLIC_UNRESOLVED`/`DEPTH_MULTI_DIM_UNRESOLVED`, with the
raw expression text kept verbatim rather than rounded to a plausible number. WIDTH is resolved the
identical way from the signal's own packed data-type text; a scalar base type with no packed range
is a real, resolved 1-bit width, not an absence, while a typedef/struct-shaped type this module
cannot decompose is `WIDTH_UNRESOLVED_TYPE`, citing the real type text. READ/WRITE PORT roles come
from the module's own declared ports, matched by naming convention against a small, disclosed,
fixed token vocabulary (wr/write/wen/push/waddr/wdata/wptr vs. rd/read/ren/pop/raddr/rdata/rptr) --
labelled `PORTS_MATCHED_BY_NAMING_CONVENTION`, a materially weaker claim than the array-derived
facts and never presented at the same confidence; a port name matching both vocabularies is
excluded from both lists rather than guessed into either, and a module matching neither reports
`PORT_DIRECTION_NOT_DETERMINABLE_FROM_NAMING` rather than a guessed single-/dual-port classification.

**Deliberately bounded, and stated rather than implied closed.** No elaboration -- a
`generate`/`` `ifdef ``-guarded array declaration is reported exactly as `verible_parser.py` itself
already reports it, present unconditionally, since this is a parser, not an elaborator. No
cross-module resolution of a parameter overridden at instantiation -- a resolved-via-parameter
depth/width uses only that module's own declared default. No simulation, waveform, or register-map
evidence of any kind. It decides, approves and arbitrates nothing beyond its own extraction: no
build, job, or approval is touched, and there is deliberately no stage gate. `cli.py`/`gates.py`
were not touched, matching several other recent modules in this codebase under the same
concurrent-edit-pressure file-safety scope -- the front door is the standalone
`python -m dv_harness.memory_buffer_arch_extraction` verb.

Proven by `dv_harness_tests/test_memory_buffer_arch_extraction.py` (44 tests, re-run for this
audit: `44 passed` in 2.37s): a two-tier design -- pure unit tests against hand-built `ModuleInfo`/
signal shapes needing no verible binary, plus real-subprocess tests against a real
`verible-verilog-syntax` install (skipped, never faked, on a machine without it) -- including the
required negative control proving a module with no memory/FIFO/buffer signal reports
`NOT_AVAILABLE` rather than a fabricated structure, and the literal/parameter-default depth/width
resolution paths each proven against real parsed RTL.


<!-- S269: moved verbatim from CLAUDE.md original lines 15898-15975 (M4.6 CLAUDE Context Normalization) -->
## Knowledge Conflict Resolver: Memory-Tier Conflicts, Never a Document-Source Conflict (2026-09-06, section 229)

`source_authority.py`'s own 9-level `AUTHORITY_ORDER` and `resolve_conflict()` decide which of two
already-read DOCUMENT/artifact sources (simulation result, RTL, register file, controller doc, VIP
example, ...) is true, by a fixed authority order a human wrote down once -- a genuinely different
question from this item's: two records already living in this project's own 5-tier MEMORY store (see
`memory.py`'s `MEMORY_LEVELS`) state DIFFERENT claims about the SAME subject -- concretely, a
`kind="verified_fix"`/`"root_cause"` record at Engineering tier states a root cause a
`promote_to_organizational()`-minted Organizational-tier record for the same protocol does not agree
with. A repo-wide grep for `knowledge_conflict`/`KnowledgeConflict`/`memory_conflict`/
`MEMORY_CONFLICT` before this module was written found nothing.

`dv_harness/knowledge_conflict_resolver.py` closes exactly that gap, and its own docstring states why
memory tier is NOT a second authority order: this project's Core Operating Rules state plainly "Memory
is prior knowledge, not current evidence" and "Any current root cause must be revalidated with current
evidence" -- Organizational tier certifies a claim was independently RE-DERIVED at least twice under a
qualitative/confidence/confirmation-count bar (`memory_router.ORGANIZATIONAL_MIN_CONFIRMATIONS`), never
that the claim is still true today. So unlike `AUTHORITY_ORDER`, memory tier carries NO fixed rank a
conflict can be resolved against mechanically: `resolve_memory_conflict()` never returns a "which one
wins" verdict, only `NO_CONFLICT` / a genuine `MEMORY_TIER_CONFLICT` / `NOT_COMPARABLE_DIFFERENT_
SUBJECT` -- and every `MEMORY_TIER_CONFLICT` is mandatory human escalation, exactly like
`source_authority.resolve_conflict()`'s own `UNDECIDABLE_SAME_AUTHORITY` case, applied here to EVERY
disagreement rather than only a same-rank tie (because for memory records, every pair is effectively a
same-rank tie -- there is no rank at all).

**REUSE, NOT REINVENT -- the escalation half.** `source_authority.escalate_conflict()` cannot be called
directly here: it builds a `SourceClaim` per side, and `SourceClaim.__post_init__` calls
`normalize_source()`, which raises on anything outside the 9 `AUTHORITY_ORDER` ids/aliases --
"engineering_memory tier"/"organizational_memory tier" are not, and were never meant to be, members of
that list. What this module reuses instead is the REAL, SANCTIONED generalization of
`escalate_conflict()`'s own question-queue mechanism: `question_queue.build_multiple_choice_question()`
(added the same day this module was built, in `question_queue.py` itself), whose own docstring states it
is "the N >= 2 generalization of `source_authority.escalate_conflict()`'s exactly-2-option shape", and
that it "reuses this module's own `add_question()` / `make_question_key()` exactly as `escalate_
conflict` already does -- there is no second filing mechanism." `escalate_memory_conflict()` calls that
function directly: same Q-ID derivation, same Tier-3 (`affects_spec_intent`) classification, same
per-option evidence-path citation and the same idempotent-on-`question_key` re-filing discipline
`escalate_conflict()` uses.

**What it does.** `extract_memory_claim()` turns one raw `MemoryStore` record into a `MemoryClaim` --
refusing (never guessing) a record missing a tier, a `memory_id`, a subject (`protocol`), or a reusable
claim field (`memory_router.ENGINEERING_REUSABLE_CLAIM_FIELDS` -- imported, not re-typed: "root_cause"/
"fix"/"lesson", the same fields `memory_router.engineering_admission_gate()` already requires for a
record to be a "reusable claim" at all). `resolve_memory_conflict()` compares one Engineering-tier claim
against one Organizational-tier claim about the supposedly-same subject and reports `NO_CONFLICT` (same
claim, normalized), `NOT_COMPARABLE_DIFFERENT_SUBJECT` (different subject -- comparing them at all would
be the fabrication this module exists to refuse), or `MEMORY_TIER_CONFLICT` (a real, textual
disagreement -- mandatory escalation, never a resolved value; there is deliberately no "winner" field,
unlike `source_authority.resolve_conflict()`'s `winner`/`losers`). `escalate_memory_conflict()` files
that conflict as a real blocking question, or returns `None` for a `NO_CONFLICT`/`NOT_COMPARABLE`
verdict (agreement, or an apples-to-oranges pair, is not a question). `find_tier_conflicts()` is the
convenience detector: it scans a real `MemoryStore`'s ACTIVE Engineering/Organizational records and
reports every real conflict among them, skipping (never crashing on) any record this module cannot even
extract a claim from.

This module authors no conclusion, decides no protocol, and picks no winner. It only detects a genuine,
evidence-cited disagreement between two memory tiers and files it where a human already answers
everything else this project cannot decide mechanically: the real question queue.

Proven by `dv_harness_tests/test_knowledge_conflict_resolver.py` (22 tests), real machinery throughout: a
real `MemoryStore` writes both tiers' records exactly as `engine.py`'s `_promote_verified_fix_
knowledge()`/`memory_router.promote_to_organizational()` shape them, and every escalation test drives a
real `QuestionQueueStore` on disk and reads the persisted question back out of it -- nothing is mocked.
The headline negative control, `test_real_conflict_is_reported_and_never_resolved_to_a_winner`, asserts
there is no `winner`/`losers` field on a `MEMORY_TIER_CONFLICT` result and that the rule text explicitly
states neither tier is trusted mechanically -- contrasting `source_authority.resolve_conflict()`'s own
legitimate `RESOLVED` verdict for document sources. Further negative controls: a record missing a
tier/subject/reusable-claim field is refused rather than silently compared; two records about genuinely
different subjects are `NOT_COMPARABLE`, never fabricated into a conflict; agreement and non-
comparability both ask nothing; re-escalating an identical conflict never grows the queue; and a
whole-store scan skips a malformed record rather than crashing. Re-verified in this pass:
`python -m pytest dv_harness_tests/test_knowledge_conflict_resolver.py -q` -> `22 passed`.

**Deliberately bounded**: this closes the Engineering-vs-Organizational pairing this item's own scope
names. A same-tier pairing (two Engineering records, or Project vs Working) is a different, unbuilt
question, and `resolve_memory_conflict()` refuses any other tier pairing (`WRONG_TIER_PAIR`) rather than
silently widening scope to one it was never asked to reason about.


<!-- S272: moved verbatim from CLAUDE.md original lines 16072-16148 (M4.6 CLAUDE Context Normalization) -->
## Verification Knowledge Graph: Real TEST/REQUIREMENT/COVERAGE/ROOT_CAUSE Linking (2026-09-06)

Sections 117-118's "a real queryable graph linking tests/requirements/coverage-bins/root-causes",
built by `dv_harness/verification_knowledge_graph.py`. **Distinct from `design_knowledge_correlation.py`**,
confirmed by re-reading that module before writing this one: that is a generic engine over an
arbitrary number of caller-declared "design knowledge fact" sources (SOURCE/FACT nodes, ASSERTS
edges), deliberately importing nothing from `dv_harness` itself so it stays domain-agnostic. This
module answers a different, fixed-shape question specific to THIS project's own three real
producers -- `evidence_db.py`, `requirement_contract.py`, `memory.py` -- and imports all three
directly; neither module imports the other, and neither's node/edge vocabulary overlaps the other's.

**Real sources, never invented nodes/edges.** Read via `EvidenceStore.query(sql, params)` -- the
same generic read-back convention `change_impact.py`/`consolidated_kpi_benchmark.py`/
`coverage_analysis.py` already use, no second evidence reader written here:
- `golden_scenarios.test_name` + `.requirements_json` (`golden_scenario.GoldenScenario.requirements`)
  is the **only** place in this codebase a test is explicitly declared to verify a set of real
  requirement ids -- the sole source of `TEST --VERIFIES--> REQUIREMENT` edges. No name-similarity or
  protocol-equality guessing (many tests share a protocol; that would over-link).
- `failure_signatures.pattern` + `.root_cause_hint` -- `TEST --HAS_ROOT_CAUSE--> ROOT_CAUSE` edges. A
  row with a null `root_cause_hint` (a real, unresolved failure) surfaces as an
  `unresolved_failure_signatures` marker on the TEST node -- never a fabricated ROOT_CAUSE node.
- `coverage_samples.category_name` (+ `.source`) -- `COVERAGE_CATEGORY` nodes, linked to a TEST node
  only on an exact-string `source` match to an already-known test pattern (the same literal,
  never-fuzzy join `design_knowledge_correlation.py`'s own `fact_key` match commits to). An unmatched
  `source` still yields the category node, just unlinked -- coverage here is honestly
  category-level, this project's real granularity (`parse_coverage_summary()`'s own
  `{name, percent, bins_total, bins_hit}` shape has no per-named-bin detail anywhere in this codebase
  today).
- Caller-supplied `requirement_contract.py`-shaped records: each must `declares_contract_shape()` and
  carry `requirement_id`, or the build raises `VerificationKnowledgeGraphError` (fail-closed, never a
  silently-dropped malformed record). `requirement_contract.derive_status()` -- re-derived from real
  content, not the record's own self-declared `status` -- lands on the REQUIREMENT node as
  `derived_status`, alongside the record's own `declared_status` unchanged, so an overclaiming record
  is visible on the graph exactly as `requirement_contract.py` itself would report it.
- `memory.MemoryStore.find(kind=...)` over the real root-cause-shaped kinds `memory_router.py`
  already routes (`root_cause`/`verified_fix`/`debug_lesson`/`job_failure`/`job_result` --
  `ROOT_CAUSE_MEMORY_KINDS`, no new kind vocabulary). A record's `pattern` field (present on job-tier
  records, genuinely absent on many standalone RCA records) is the **only** thing that earns it a TEST
  edge -- no pattern, no edge, never a guessed test. Root-cause node identity
  (`root_cause_node_id(protocol, text)`) is a `(protocol, normalized text)` key shared with the
  `evidence_db` path, the same equivalence `memory.py`'s own closed-finding "same finding" dedup
  already uses -- proven (in `test_memory_and_evidence_db_root_cause_converge_on_one_node`) to
  converge the exact same real root cause, recorded independently via both paths, onto one node with
  two provenance entries rather than fabricating two.

**Queryable, not just constructed.** `VerificationKnowledgeGraph` exposes `tests_verifying_requirement`,
`requirements_verified_by_test`, `root_causes_for_test`, `coverage_for_test`, the two-hop
`root_causes_for_requirement` (REQUIREMENT <-VERIFIES- TEST -HAS_ROOT_CAUSE-> ROOT_CAUSE, including
verified tests with an empty root-cause list -- a real, distinct fact from no verifying test at all),
and `traceability_gap_report()` -- a **worst-wins** rollup: any one REQUIREMENT node with zero
incoming VERIFIES edges makes the whole rollup `GAPS_PRESENT` regardless of how many others are
clean, never averaged; honestly `NOT_APPLICABLE` when no requirement records were ever supplied
(nothing to have a gap in).

**Deliberately bounded.** (1) No arbitration -- two contract records disagreeing on the same feature
stays `requirement_contract.cross_source_contradictions()`'s own question. (2) No RTL/register/design
correlation -- `dut_evidence_correlation.py`/`design_knowledge_correlation.py`'s own territory. (3)
Coverage is category-level only, per this project's real evidence granularity today. (4) No `cli.py`
verb (out of this task's file-safety scope per house style); front door is
`python -m dv_harness.verification_knowledge_graph --evidence-db <path> --requirements <file.json>
[--memory-root <path>] [--json]`, matching `design_knowledge_correlation.py`'s own precedent.

Proven by `dv_harness_tests/test_verification_knowledge_graph.py` (28 tests, real `EvidenceStore`
DuckDB and real `MemoryStore`, no mocks) -- every positive linking assertion (golden-scenario VERIFIES
edge, failure-signature root cause, coverage exact-match, memory root-cause edge, cross-source
convergence, worst-wins gap report, two-hop query) is paired with a negative control proving the
absence case: a null `root_cause_hint` never fabricates a ROOT_CAUSE node; an unmatched coverage
`source` stays unlinked; a standalone RCA record with no `pattern` stays test-unlinked; a
verified_fix record with no root-cause text is skipped and logged, never turned into an empty node; a
golden_scenario citing an unsupplied requirement id gets an honest `contract_available: False` stub;
a malformed requirement record and one missing `requirement_id` both raise
`VerificationKnowledgeGraphError`; a stale evidence.duckdb missing a table (`DROP TABLE
golden_scenarios`) is reported in `notes`, never crashed on; plus CLI subprocess tests for the clean
`GAPS_PRESENT`/exit-1 path, the malformed-input/exit-2 path, and the nonexistent-`--evidence-db`
warn-and-continue path. Re-verified in this integration pass:
`python -m pytest dv_harness_tests/test_verification_knowledge_graph.py -q` -> `28 passed`.


<!-- S275: moved verbatim from CLAUDE.md original lines 16271-16363 (M4.6 CLAUDE Context Normalization) -->
## Self-Learning Readiness Matrix: `python -m dv_harness.self_learning_readiness` (2026-09-06)

Section 55's SELF-LEARNING READINESS MATRIX (22 rows over the
research/capability-evolution and five-tier-memory surfaces) was the exact gap
`golden_flow_readiness.py`'s own CLAUDE.md section disclosed as NOT_BUILT --
"a different row set over different sources, and producing a half-sourced
version of it would be the fabrication this module exists to prevent."
`dv_harness/self_learning_readiness.py` is that different row set.

**It copies `golden_flow_readiness.py`'s pattern exactly, over disjoint
sources.** Same READY/PARTIAL/BLOCKED/UNKNOWN vocabulary (reused from
`subsystem_discovery`, not reminted), same worst-wins `combine_readiness()`,
same `fact_source`-per-row provenance with its own
`assert_fact_sources_resolvable()` (proves all 40 declared dotted references
still resolve through the import system -- verified: len==40, no raise), same
`inference.next_best_action()`-driven Next-Best-Action column through a
row-keyed `gap_action_catalog`. None of `golden_flow_readiness.py`'s twenty
rows are repeated, and none of this module's 22 rows read `dashboard.py`,
`gates.py` or `env_manifest.py` -- the two matrices are deliberately disjoint,
reading `capability_evolution.py` (research evidence cards, prior-research
contradiction/supersede links, the 10-question L5 check, overlap/
recommendation decisions, the 11-state promotion machine, human approval,
controlled-experiment benchmark evidence, shadow-replication stability
windows, production rollback history, repeated-failure auto-filing, the
candidate audit trail, architecture decision history), `memory.py`/
`memory_router.py` (index integrity, Engineering/Organizational admission
health, the revalidation queue, the retraction/supersede ledger, confirmed-
conclusion accumulation, the Corner-Case Library) and `confidence_calibration.py`/
`cross_project_mining.py` (tier calibration, the cross-project registry and
pattern miner) instead.

**Admission health rows RE-VERIFY rather than trust a stored flag.**
`engineering_admission_health` and `organizational_admission_health` re-run
`memory_router.engineering_admission_gate()`/`organizational_admission_gate()`
against every REAL stored record of that tier -- not a fresh record being
admitted, an ALREADY-stored one being asked "does this still clear the gate
today". Run against this repository's own real, years-of-use memory store, it
found 30 of 31 real Engineering-tier records no longer clear the current gate
(most carry no `evidence` field), correctly reporting BLOCKED rather than
trusting their stored `"confidence": "HIGH"`. It also found this repo's own
`corner_case_library/index.json` reports zero cases while 21 real per-case
record files sit on disk -- the exact index/file "lost update" class
`memory.py`'s own `MemoryStore.index_integrity()` docstring already documents
as a previously-measured real defect in this project, now caught for the
Corner-Case Library too. Neither finding is a bug in this module; both are
honest facts this module exists to surface rather than paper over.

**Read-only, and provably so.** `MemoryStore`, `Blackboard` and `ControlPlane`
all `mkdir()` (or, for `ControlPlane.load()`, MINT a fresh `control.json`) on
construction, so every such constructor is called ONLY after a plain
file-existence check proves the artifact it owns already exists --
`test_empty_project_all_22_rows_unknown_and_no_dv_harness_tree_created` proves
a fresh project gets 22 honest UNKNOWNs and zero `.dv-harness/` created, and
`test_populated_project_is_byte_identical_after_a_read` proves an
already-populated project's files are byte- and mtime-identical after a run.

**Disclosed residuals, matching this project's own "Deliberately bounded"
convention:**

  * **No CLI subcommand.** `dv_harness/cli.py` was left untouched per this
    batch's own instruction that it is under heavy concurrent edit pressure;
    `python -m dv_harness.self_learning_readiness [--project-root R] [--json]`
    is the front door, the same disclosed choice several recent modules in
    this codebase already made.
  * **Not engine-fired, not on the dashboard.** No `run_stage()`/`advance()`
    call site invokes it and no graph node declares it -- a REACHED
    capability, not a WIRED one, exactly as section 55's own residual text
    said of `golden_flow_readiness.py`.
  * **The 22 row labels are this module's own declaration, not a
    transcription.** Section 47 names its twenty rows one by one, so
    `golden_flow_readiness.py` could transcribe them verbatim and check
    against that transcription. Section 55 names the row count (22) and the
    two surfaces but not individual row labels -- there is no spec text at
    that granularity to transcribe. `SELF_LEARNING_ROW_LABELS` is therefore
    frozen and checked against `ROWS` itself (catches a row silently dropped
    or renamed later), never claimed to be transcribed from section 55.

Proven against real, separately-constructed project trees --
never against this repository as its own two-project cross-project sample --
in `dv_harness_tests/test_self_learning_readiness.py` (22 tests,
`python -m pytest dv_harness_tests/test_self_learning_readiness.py -q` ->
`22 passed`). Every fixture is a real writer (`MemoryStore`/`MemoryGC`/
`MemoryConsolidator`, `Blackboard`, `ControlPlane.approve()`,
`capability_evolution.build_candidate()`/`persist_candidate()`/
`file_candidates_for_repeated_failures()`, `CornerCaseLibrary.add()`,
`memory_router.route_and_store()`, `cross_project_mining.ProjectRegistry.register()`),
and its negative controls are what give it detection power: a HIGH-confidence
engineering record that no longer clears the real gate reads BLOCKED, a
corner-case index that undercounts real record files reads BLOCKED, 3
confirmed outcomes (below the real 10-outcome calibration bar) stays honestly
UNKNOWN rather than a fabricated CALIBRATED, and a fresh project stays
all-UNKNOWN with zero state minted. Also driven as a real CLI subprocess.


<!-- S277: moved verbatim from CLAUDE.md original lines 16443-16536 (M4.6 CLAUDE Context Normalization) -->
## User-Correction-Triggered Capability-Evolution Gap Detection (2026-09-06)

Research_Capability_Evolution_Master_Prompt sections 64/66's OTHER half. `capability_evolution.py`'s
"Cross-Loop Coupling" section already auto-files a DISCOVERED capability-evolution candidate when the
SAME failure signature recurs across independent runs with no gate-verified `verified_fix`. Nothing
closed the sibling case section 64 also names: a HUMAN repeatedly correcting the SAME KIND of agent
mistake. A repo-wide grep for `user_correction`/`correction_trigger`/`repeated.*correction` before this
change returned nothing executable.

`dv_harness/user_correction_trigger.py` closes it, reusing rather than duplicating on every axis. The
evidence is `dv_harness/memory.py`'s OWN, already-coded correction lifecycle -- `MemoryGC.retract()`
("the record was found to be wrong outright") and `MemoryGC.supersede()` ("a newer, corrected record
replaces this one", verbatim from that method's own docstring), both of which set a real persisted
`status` (`RETRACTED`/`SUPERSEDED`) plus a real cited reason (`retraction_reason`/`supersede_reason`) on
the same per-tier `MemoryStore` record files -- there is no second correction log anywhere in this
module, and none was invented. `confidence_calibration.py` already treats both statuses as "a rejected
outcome" for its own domain (tier reliability), confirming these are real, already-tested writers this
codebase relies on elsewhere. The LESSON half is `kind in ("debug_lesson", "root_cause")` -- this
codebase's own literal "lesson" vocabulary -- carried onto a filed candidate purely as informational
context (`referenced_by_lesson`), never as a closure gate (see below).

**"Repeatedly corrected the same kind of mistake" means**: two or more INDEPENDENT memory records
(distinct `memory_id`s -- each is one correction event, since `retract()`/`supersede()` mutate one
record file in place) whose cited correction reason normalizes to the SAME text, matched by EXACT
equality (never fuzzy), the identical "exact equality ... never fuzzy" discipline
`capability_evolution.failure_resolution_claims()`'s own docstring already states the reason for.
Grouping reuses `evidence_db.signature_key()` -- the same stable-hash utility the sibling failure-pattern
filer already depends on, not a second hashing definition.

**DISCOVERED-only, human-approval-gated, identical posture to the failure-pattern filer.** Every filed
candidate goes through the REAL `capability_evolution.build_candidate()`/`persist_candidate()`/
`read_candidate()`/`transition()` -- no parallel candidate constructor -- so the recommendation stays
DERIVED and confidence stays recomputed through the real `inference.score_confidence()`. All six
`existing_*` search slots are filed `search_conclusive: false` with an honest `search_basis` (never a
fabricated MISSING/ADD). `file_user_correction_candidate()` mirrors
`file_repeated_failure_candidate()`'s exact three-outcome shape (`ALREADY_BEYOND_DISCOVERED` /
`ALREADY_ON_FILE_UNCHANGED` / filed), including the content-derived `candidate_id` that lets a later
cycle accumulate evidence on the SAME record rather than forking a duplicate. `capability_evolution.py`
itself was NOT edited -- every symbol this module needs from it was already public.

**NO CLOSURE CONCEPT, disclosed rather than invented.** Unlike the failure-pattern filer's
`verified_fix` (a gate-verified "this specific failure was fixed"), nothing in this codebase
gate-verifies "this class of correction can no longer happen" -- inventing one would be exactly the
fabrication the Evidence Truth Rule forbids. The only thing that stops a pattern from being re-filed is
`ALREADY_BEYOND_DISCOVERED` -- a human (or a `research-architect` pass) moving the candidate off
DISCOVERED -- mirroring the failure filer's identical guard exactly.

**Honestly disclosed: `retract()`/`supersede()` are reachable, not yet wired.** Confirmed by direct
search before writing this module: `MemoryGC.retract()`/`supersede()` have ZERO production callers
anywhere in `dv_harness/*.py` today. `memory_cli.py`'s only human-facing lifecycle verb is `deprecate`
(a DIFFERENT status, `DEPRECATED` -- "retired, not refuted"); the one CLI surface that DOES name
RETRACTED (`dv-harness knowledge deprecate`) calls the REMOTE, opt-in Knowledge Center broker, not this
project's local `.dv-harness/memory` tree this module reads, and requires a live server connection this
module neither establishes nor depends on. So this repository's own real answer today is that zero
repeated-correction patterns exist to detect -- the same honest "no production result exists yet"
disclosure `cross_project_mining.py`/`syoscb_source_audit.py` already make for their own domains. The
mechanism is proven against REAL `MemoryGC.retract()`/`supersede()` calls (never hand-written JSON), and
fires the moment any real caller -- a future local CLI verb, or a human using the existing remote one --
starts producing them.

No `dv-harness` CLI verb was added and `cli.py`/`gates.py` were not touched (this item's own explicit
instruction); the front door is `python -m dv_harness.user_correction_trigger detect|file
[--min-occurrences N] [--root DIR]`, exit 0 nothing found / 1 a pattern was detected or filed.

Proven by `dv_harness_tests/test_user_correction_trigger.py` (18 tests, `python -m pytest
dv_harness_tests/test_user_correction_trigger.py -q` -> `18 passed`), every correction record built
through the REAL `MemoryGC.retract()`/`supersede()` methods -- never hand-written JSON. Covers: a single
correction never fires (section 64's own warning); two independent RETRACTED occurrences of the same
normalized reason DO fire; RETRACTED and SUPERSEDED records sharing one reason combine; re-retracting
the SAME `memory_id` twice is still one occurrence, never two; two genuinely different reasons stay two
separate patterns (the exact-match negative control); a `DEPRECATED` record is never counted as a
correction; a blank reason is never counted; a matching `debug_lesson` record is carried as
`referenced_by_lesson` but never suppresses filing (the NO-CLOSURE proof); the filed candidate is real
persisted DISCOVERED state with a verified Working Memory audit record and every cited `memory_id`
resolving on disk; the six search slots are honestly `search_conclusive: false`; the `candidate_id` is
stable and accumulates evidence across cycles; re-filing unchanged evidence writes nothing; a
human-moved candidate is never dragged back (`ALREADY_BEYOND_DISCOVERED`); the schema structurally
refuses `PROPOSED` while any search stays unresolved; `HumanApprovalRequiredError`/
`ProductionWriteNotAuthorizedError` are asserted untouched; the candidate never reaches a tier above
`WORKING_MEMORY`; and both CLI exit codes are driven end to end. Re-run in this integration pass
alongside its two reused-module regression suites: `test_capability_evolution_auto_discovery.py`
(23 passed) and `test_confidence_calibration.py` (35 passed) -- combined `76 passed`.

**Disclosed residual**: this closes the DISCOVERY half only, exactly like the sibling failure-pattern
filer's own disclosed residual. It is REACHED, not WIRED -- no `run_stage()`/`advance()` call site
invokes it and no graph node declares it. Grouping is exact-text-equality only (a real, disclosed
under-detection trade: two occurrences of "the same kind of mistake" worded even slightly differently
will not be grouped, since `retraction_reason`/`supersede_reason` are free text, unlike a
`build_failure_signature()` dict built by one shared function specifically to be byte-identical across
occurrences of the same failure). And, as stated above, `MemoryGC.retract()`/`supersede()` have no
production caller in this repository yet, so a real repeated-correction pattern has never actually fired
here -- the mechanism is proven against real writer calls, not made to "have fired" by writing fabricated
correction records into this project's own real memory store.


<!-- S282: moved verbatim from CLAUDE.md original lines 16805-16863 (M4.6 CLAUDE Context Normalization) -->
## Human Correction Learning (2026-09-06, section 227)

Spec section 227 (Research_Capability_Evolution master prompt) asks for a mechanism that captures
and structures a human's correction of an agent mistake as a REUSABLE lesson record, so a future
session can query "has a human corrected this exact mistake before" instead of re-deriving the same
wrong answer and needing a second human correction. `dv_harness/memory.py` already has a
`kind="debug_lesson"` route into Engineering Memory, and `engine._promote_experience_knowledge()`'s
own comment already names what a `debug_lesson` is for ("captures what this class of problem looks
like / why / when it applies") -- but every existing `debug_lesson` writer stores free text only
(`root_cause`/`fix`/`lesson` strings), so nothing could ever answer "was this SPECIFIC agent mistake,
as stated, already corrected by a human once" without a human re-reading prose.

`dv_harness/human_correction_lesson.py` is exactly that extension: it builds and validates a
`kind="debug_lesson"` record whose `correction` field is schema-shaped (before/after, section 227's
own vocabulary), and it is the ONLY code in this repository that writes that shape --
`route_and_store()`/`route_memory()`/`engineering_admission_gate()` in `memory_router.py` are
called, not duplicated, so a record this module builds is admitted to the Engineering tier by the
exact same real gate every other `debug_lesson`/`root_cause`/`verified_fix` record already goes
through.

**Distinct from `dv_harness/user_correction_trigger.py`** (checked by direct reading before this
module was written, so the two are not a collision under two names). That module detects
REPETITION of a correction (two or more independent `MemoryGC.retract()`/`supersede()` events
citing the identical normalized reason) and, on repetition, files a capability-evolution candidate
asking "should this harness grow a guard against this class of mistake" -- it never structures a
single correction's own before/after content. `human_correction_lesson.py` is that missing
mechanism: it captures ONE correction, structured, the moment it happens (no repetition required),
and answers a query about ONE exact mistake ("has this happened before") rather than filing a
capability-evolution proposal about a recurring pattern. The two compose naturally but neither
imports the other.

**"This exact mistake" means exact equality, never fuzzy.** `mistake_signature_key()` hashes
`{mistake_category, normalized before.claim text}` with `evidence_db.signature_key()` -- the SAME
stable hash utility `capability_evolution.repeated_unresolved_failure_patterns()` and
`user_correction_trigger.correction_signature_key()` already use, rather than a second hashing
definition. Two occurrences of what a human would call "the same mistake" worded even slightly
differently will NOT be matched by `find_prior_corrections()` -- a real, disclosed limitation:
under-detection, never fabricated over-detection, is the accepted trade, matching
`user_correction_trigger.py`'s own docstring's identical reasoning.

**What it deliberately does not do.** It never decides whether the human's correction is itself
correct -- the Evidence Truth Rule stops at "a human, cited, corrected this"; it is not a second
verification pass over the human's own claim. It never re-implements `memory_router`'s tier routing
or admission gates -- `record_human_correction_lesson()` calls `route_and_store()` exactly once and
returns whatever it decides, including the honest demotion-to-Working-Memory outcome should a
caller build a record that fails `engineering_admission_gate()`. It never fabricates a match --
`find_prior_corrections()`/`has_prior_correction()` return an honestly empty result when nothing
matches, never a guessed "probably yes".

There is no `dv-harness` CLI verb (`cli.py`/`gates.py` untouched, matching several sibling same-day
modules' own disclosed choice) -- the front door is `execute_verb()`/`python -m
dv_harness.human_correction_lesson`.

Proven by `dv_harness_tests/test_human_correction_lesson.py` (18 tests, `python -m pytest
dv_harness_tests/test_human_correction_lesson.py -q` -> `18 passed`), verified in this pass against
a real `MemoryStore` on disk: real record construction/validation, the exact-match signature key
(including its deliberate under-detection on slightly-reworded text), a real `route_and_store()`
admission round trip, and the honest-empty-result negative control when no prior correction exists.


<!-- S322: moved verbatim from CLAUDE.md original lines 19486-19561 (M4.6 CLAUDE Context Normalization) -->
## DUT-fact Design Knowledge Graph (2026-09-07)

`dv_harness/dut_knowledge_graph.py` builds a real, queryable GRAPH over already-extracted DUT-side
facts -- RTL modules, register fields, PHY-architecture states, interrupts, and clocks/resets -- as
typed nodes with real, cited edges, assembled ONLY from rows this project's own real extractors
already produced: `design_architecture_ir.py` (module registry + instance tree),
`register_rtl_trace.py` (per-field RTL trace results), `interrupt_dma_clock_reset_extraction.py`
(interrupt/clock/reset facts), and `phy_model_behavior_ir.py` (PHY training/TX/RX/power-state
facts). It is deliberately distinct, by name and by import, from two existing graph modules so
neither is mistaken for the other: `verification_knowledge_graph.py` is a TEST/REQUIREMENT/
COVERAGE_CATEGORY/ROOT_CAUSE graph over `evidence_db.py`/`requirement_contract.py`/`memory.py` --
a verification-closure question with no DUT/RTL model at all; `design_knowledge_correlation.py` is
a generic, domain-agnostic CONFLICT/GAP/DOCUMENTED_VS_IMPLEMENTED correlator over an arbitrary
number of caller-declared fact sources, deliberately importing nothing from `dv_harness` itself so
it stays reusable. This module answers a third, fixed-shape question neither of those two can:
given this project's own four real DUT-fact extractors, what is the DUT's own architecture --
which module instantiates which, which register field traces to which real RTL port/signal, which
interrupt/clock/reset was declared in which file, and which PHY-architecture fact describes which
real PHY/controller module's boundary.

**Real sources, never invented.** A `design_architecture_ir.build_architecture_ir()` document
whose `status` is not `"BUILT"` contributes zero RTL_MODULE/INSTANTIATES facts and is recorded in
`notes` -- never a fabricated empty-but-clean module set. `register_rtl_trace.
trace_register_fields()` results add a REGISTER_FIELD node for every result supplied, but a real
RTL edge only for `TRACE_CONFIRMED` (`TRACED_TO`, one candidate) and `TRACE_PARTIAL`
(`AMBIGUOUSLY_TRACED_TO`, one edge per real candidate, never resolved to a winner, matching that
module's own refusal to pick one); `TRACE_NOT_FOUND`/`BLOCKED` add the node with its real status
and no edge. `interrupt_dma_clock_reset_extraction.py` facts are read only when that facet's own
`status` is `"LOADED"`; DMA facts are a disclosed residual (see "Deliberately bounded" below).
`phy_model_behavior_ir.py` facts are read only when that field's own status is `"FOUND"`, each
carrying its real citation plus a read-only pass-through of `phy_boundary.py`'s own bind-location
decision.

**Cross-linking is evidence-based, never name-guessed.** `register_rtl_trace.py` and
`phy_model_behavior_ir.py` both cite real module names that also appear in
`design_architecture_ir.py`'s own real module registry -- an edge to an RTL_MODULE node is only
ever added when that exact name is present in the SAME build's real registry, never assumed.
Interrupt/clock/reset facts carry a real `path:line` citation but no module name at all;
`DECLARED_IN_FILE` links each one to every RTL_MODULE this build parsed from that SAME file path
(normalized, exact-string match, never fuzzy), honestly flagged `file_match:
"ambiguous_multi_module_file"` when that file declares more than one module -- this module never
guesses which one a bare file-level fact "really" belongs to.

**Queryable, not just constructed.** `DutKnowledgeGraph` exposes `neighbors()`,
`rtl_sites_for_register()` (a register field's real confirmed + ambiguous RTL backing in one call),
`unresolved_registers()`, `interrupts_in_module()`/`clocks_in_module()`/`resets_in_module()`, and
`traceability_gap_report()` -- a worst-wins rollup over every REGISTER_FIELD node this graph holds
(ANY register with zero `TRACED_TO` edges makes the whole rollup `GAPS_PRESENT`, never averaged)
that is honestly `NOT_APPLICABLE` when no register trace results were ever supplied at all, rather
than reporting a clean pass.

**Deliberately bounded.** (1) No arbitration -- an `AMBIGUOUSLY_TRACED_TO` register field with
several candidates is reported with every real candidate, never resolved to one, mirroring
`register_rtl_trace.trace_register_field()`'s own refusal for a `TRACE_PARTIAL` result. (2) No
DMA nodes -- `interrupt_dma_clock_reset_extraction.py` also extracts DMA channel-count/descriptor
facts, but this module's assigned scope is "RTL modules, registers, PHY states, interrupts,
clocks"; DMA is a real, disclosed residual, not silently folded into another node kind. (3) No
arbitration between two DIFFERENT extraction runs disagreeing about the same fact -- that stays
`design_knowledge_correlation.py`'s own, different, question, deliberately untouched and not
imported here. (4) No CLI verb -- `cli.py`/`gates.py`/`dashboard.py` are out of this task's
file-safety scope per house style; `python -m dv_harness.dut_knowledge_graph` is the front door,
matching `design_knowledge_correlation.py`'s and `verification_knowledge_graph.py`'s own
precedent. (5) Builds and queries only -- no gate, no stage, no memory write of its own.

Proven by `dv_harness_tests/test_dut_knowledge_graph.py`: pure, no-verible-needed unit tests
directly against the graph/ingestion primitives (node identity and merge, kind-collision refusal,
idempotent edges accumulating evidence, honest-absence handling for each of the four sources, and
malformed-input refusals), plus a full real-integration test driving all four real extractors over
a small, synthetic (never real-project) multi-file RTL fixture and a synthetic offline-distilled
PHY spec fixture -- proving every node kind and every edge kind this module declares is reachable
from real, citable evidence, and that a genuine cross-source ambiguity (two modules declared in one
file) is reported honestly rather than resolved by a guess. Skipped, never faked, on a machine with
no real `verible-verilog-syntax` on PATH. Ran `python -m pytest
dv_harness_tests/test_dut_knowledge_graph.py -q` -> all tests passed in this environment (real
verible-verilog-syntax present, so the full integration path ran rather than skipped).


<!-- S360: moved verbatim from CLAUDE.md original lines 21998-22134 (M4.6 CLAUDE Context Normalization) -->
## Confidence / Inference-Layer Engine Wiring: Closing Three "REACHED, not WIRED" Disclosures (2026-09-07)

Three real, individually-tested `inference.py`/`confidence_calibration.py`/`capability_evolution.py`
mechanisms were built earlier this same day, each with its own CLAUDE.md section correctly disclosing,
at the time, "REACHED, not WIRED -- no `run_stage()`/`advance()` call site or engine hook invokes
[it] yet": the "Confidence-Calibration Feedback Loop" section (`draft_reweighted_confidence_proposal()`
/ `file_confidence_reweight_candidate()`), the "Value-of-Information Evidence-Gathering Ranking"
section (`rank_evidence_by_information_value()`), and the "Hypothesis-Generation Bias Correction From
Retracted Hypotheses" section (`detect_hypothesis_generation_bias()` / `collect_hypothesis_shapes()`).
This section closes exactly that gap for all three, appended rather than edited into those three
sections (per this project's own append-only documentation discipline) -- their own prose is otherwise
still accurate and is left untouched; only their "REACHED, not WIRED" disclosure is now superseded by
the real engine call sites this section documents.

A prior, independent audit of this Confidence/Inference layer (read-only, no code changed) ranked
these three tasks, plus a fourth (Adversarial Refutation Pass), as the highest-priority remaining gaps
in this layer, each with its own insertion point, safety rationale and baseline test count. Before
implementing any of the three, each was re-verified against the CURRENT, live content of `engine.py`,
`inference.py`, `confidence_calibration.py`, and `capability_evolution.py` -- a fresh grep confirmed
`draft_reweighted_confidence_proposal`, `rank_evidence_by_information_value`, and
`detect_hypothesis_generation_bias` all had zero call sites anywhere in `engine.py`, matching the
audit's own finding and each module's own CLAUDE.md disclosure exactly. All three were then implemented
one at a time -- one new best-effort `engine.py` hook method plus one wired call site per task, each
followed immediately by its own new, real, end-to-end test file and a full pytest run before moving to
the next task -- following the SAME sibling try/except-wrapped hook style
`_promote_experience_knowledge()`/`_persist_subsystem_registry_entry()` already established in this
file, and never touching `route_and_store()`, `ControlPlane`, `policy.can_signoff()`, or any
gate/verdict-computing code path.

**Task 1 -- Confidence-Calibration Feedback Loop.** `DVHarness._file_confidence_reweight_candidate_
from_calibration(stage)` (new method, inserted immediately after
`_file_capability_evolution_candidates_from_repeated_failures()`, before `_maybe_run_self_tuning_
review()`) calls the real, unmodified `confidence_calibration.calibrate(self.root, cfg=self.cfg)` ->
`draft_reweighted_confidence_proposal(report)` -> `capability_evolution.file_confidence_reweight_
candidate(self.root, proposal, cfg=self.cfg)` chain -- three real functions, none re-derived, none
edited by this task. Wired at the identical call site as its sibling `_file_capability_evolution_
candidates_from_repeated_failures(stage)`, inside the existing `if stage in (Stage.FAILURE_RECOVERY.
value, Stage.RE_AUDIT.value) and ss["status"] in (Status.FAIL.value, Status.PARTIAL.value):` branch.
`calibrate()`/`draft_reweighted_confidence_proposal()` perform no write of any kind; `file_confidence_
reweight_candidate()` only ever files a `DISCOVERED`-tier `CapabilityEvolutionCandidate` (never calls
`transition()`, refuses to persist anything not at `DISCOVERED`) whose every downstream step (a real
controlled experiment, a shadow-replication stability window, a human's `HUMAN_APPROVED` decision) is
untouched and uncalled from here -- `inference.score_confidence()`'s live formula is never read,
imported, or edited. Best-effort: any exception is caught and recorded as
`CONFIDENCE_REWEIGHT_AUTO_DISCOVERY_FAILED`, never allowed to turn an already-computed FAIL/PARTIAL
stage result into a crash; every outcome, including "no proposal drafted"
(`REWEIGHT_PROPOSAL_NO_INVERSION`), is one `CONFIDENCE_REWEIGHT_AUTO_DISCOVERY` event in
`.dv-harness/events.jsonl`.

**Task 2 -- Hypothesis-Generation Bias Correction.** `DVHarness._detect_hypothesis_generation_
bias(stage)` (new method, inserted immediately after Task 1's method, before `_maybe_run_self_tuning_
review()`) calls the real, unmodified `inference.collect_hypothesis_shapes(self.root)` ->
`inference.detect_hypothesis_generation_bias(hypotheses)` and writes the result verbatim to a new
`"hypothesis_generation_bias"` Blackboard topic, mirroring `_trace_memory_lineage_for_promotion()`'s
own event-naming convention -- fired on every real status, including `NO_BIAS_DETECTED`/
`INSUFFICIENT_HISTORY`/`NOT_AVAILABLE`, not only `BIAS_DETECTED`, since "no pattern qualified" is
itself citable evidence. Wired at the same FAILURE_RECOVERY/RE_AUDIT FAIL/PARTIAL branch, immediately
after Task 1's new call. Advisory only, per that function's own docstring: it never scores a
hypothesis, never blocks a stage, and never touches `score_confidence()`'s own formula/weights.
Best-effort: an exception records `HYPOTHESIS_GENERATION_BIAS_DETECTED_FAILED` rather than crashing
the stage.

**Task 3 -- Value-of-Information Evidence-Gathering Ranking.** `DVHarness._root_cause_hypotheses_voi_
ranking(self, block, confidence_result)` (new method, inserted immediately after
`_root_cause_confidence_inputs()`, before `_react_step_inference()`) adapts `block["hypotheses"]` (the
real per-hypothesis array `root_cause_evidence_gate.py` already writes) into `inference.rank_evidence_
by_information_value()`'s own expected shape, using the caller's own INDEPENDENTLY RECOMPUTED
`confidence_result["level"]` for the SELECTED hypothesis (never its self-reported `confidence` field,
per the Evidence Truth Rule) and each alternative hypothesis's own self-declared, gate-recorded
confidence only as an advisory urgency weight. Called from `_score_root_cause_confidence()`
immediately after the existing `root_cause_confidence` Blackboard write / `ROOT_CAUSE_CONFIDENCE_
SCORED` event pair, strictly downstream of the already-computed `confidence_result`/`gap` -- it never
feeds back into either. Returns `None` (no-op, no write, no event) when `block["hypotheses"]` is
absent, empty, or carries no usable hypothesis dict. When real, it writes a new
`"root_cause_evidence_voi_ranking"` Blackboard topic and one `ROOT_CAUSE_EVIDENCE_VOI_RANKED` event.
Best-effort: an exception records `ROOT_CAUSE_EVIDENCE_VOI_RANKING_FAILED`, and the pre-existing
`root_cause_confidence` write immediately before it is proven, by a dedicated test, to still succeed
even when this new ranking step raises.

**Task 4 -- Adversarial Refutation Pass -- completed by a different, concurrently-running agent in
this same multi-agent session.** Independently re-verified rather than trusted from this session's own
CLAUDE.md prose: `react_loop.attempt_hypothesis_refutation()` and `qualified_conclusion.
RefutationAttempt`/`InvalidRefutationResultError`/`build_qualified_conclusion(..., refutation_
result=None, require_refutation_pass=False)` are all real and present in the live `react_loop.py`/
`qualified_conclusion.py` on disk (confirmed by direct grep of the current files, not by trusting the
CLAUDE.md section describing them), both new keyword defaults reproduce the pre-existing formula
byte-for-byte, and `engine.py` carries zero references to `attempt_hypothesis_refutation`,
`refutation_result`, or `require_refutation_pass` anywhere -- confirming that work's own "REACHED, not
yet WIRED" disclosure (engine.py deliberately left untouched, out of that task's own stated scope) is
accurate as written and needs no correction here. No engine-side work was done for Task 4 by this
session; it is recorded here only because the original audit's ranked list named it, and its real
completion (by another agent) closes that list's fourth item alongside this session's own three.

**Real before/after test evidence, every file touched.** `inference.py`, `confidence_calibration.py`,
and `capability_evolution.py` were read-only dependencies for this session's three tasks -- none of
their own source was edited -- and `python -m pytest dv_harness_tests/test_inference.py -q` (107
passed) and `dv_harness_tests/test_confidence_calibration.py`/`test_capability_evolution_confidence_
reweight.py`/`test_capability_evolution_auto_discovery.py` (all previously green, unaffected) confirm
none of the three regressed. `engine.py` itself was the one file this session actually edited, three
times, one task at a time:
- Baseline (before any of this session's three edits, per the original audit's own citation):
  `dv_harness_tests/test_inference_engine_wiring.py` -- 12 passed.
- Task 1: new `dv_harness_tests/test_engine_confidence_reweight_coupling.py` -- 4 passed (bare-project
  honest-`NO_INVERSION_FOUND` case; passing-stage-never-runs-the-coupling case; a real calibration-
  failure best-effort negative control via `monkeypatch`; and a real end-to-end tier-inversion,
  built through `MemoryGC.confirm()`/`retract()` on a real `MemoryStore`, filing a real persisted
  `DISCOVERED` candidate, re-run over unchanged evidence to prove idempotence).
- Task 2: new `dv_harness_tests/test_engine_hypothesis_bias_coupling.py` -- 4 passed (bare-project
  honest `NOT_AVAILABLE`; passing-stage-never-runs; a `monkeypatch` best-effort failure negative
  control; and a real biased corpus, built through `MemoryGC.retract()` on real records, surfacing a
  real `BIAS_DETECTED` finding on the Blackboard).
- Task 3: new `dv_harness_tests/test_engine_voi_ranking_coupling.py` -- 5 passed (a real 3-hypothesis
  `root_cause_evidence_gate`-shaped block producing a real VOI ranking; the no-hypotheses-field and
  empty-hypotheses-list no-op cases; a `monkeypatch` best-effort negative control proving the
  pre-existing `root_cause_confidence` write survives a ranking failure; and a direct proof that the
  ranking changes when the recomputed confidence level is forced HIGH vs. LOW, showing the SELECTED
  hypothesis's urgency weight is driven by the independently recomputed level, never its self-reported
  one).
- Combined re-run, all three new suites together (re-verified again at the end of this task, not
  merely once mid-implementation): `python -m pytest dv_harness_tests/test_engine_confidence_reweight_
  coupling.py dv_harness_tests/test_engine_hypothesis_bias_coupling.py dv_harness_tests/test_engine_
  voi_ranking_coupling.py -q` -> **13 passed**.
- Full `engine.py` regression, re-run fresh at the end of this task against the current, fully
  concurrently-edited `engine.py`/`gates.py`: `python -m pytest dv_harness_tests/test_engine_gates_
  and_routing.py -q` -> **239 passed, 0 failed** (273.44s) -- a clean run, no failures at all, an
  improvement over the original audit's own baseline note of one pre-existing unrelated failure,
  which has since been fixed by other concurrent work in this shared multi-agent session.

**Safety, restated concretely for this session's own three edits.** All three new methods are
try/except-wrapped exactly like every existing sibling hook in this class; none calls `run_stage()`,
`route_and_store()`, `ControlPlane`, or `policy.can_signoff()`; none mutates `ss["status"]`, a gate
verdict, or any value `gates.py`/`policy.py` reads to decide PASS/FAIL/routing; and every one of the
three new Blackboard topics/events is additive (a brand-new topic/event name, never an edit to an
existing one), so a project that has never triggered the FAILURE_RECOVERY/RE_AUDIT FAIL/PARTIAL branch
sees byte-identical behavior to before this session.



<!-- S063: moved verbatim from CLAUDE.md original lines 3436-3538 (M4.6 CLAUDE Context Normalization) -->
## Cross-Project Pattern Mining: What Recurs Across Projects (2026-09-05, VI-2)

`capability_evolution.repeated_unresolved_failure_patterns()` already mines ONE
project's Job Memory for a failure signature several INDEPENDENT RUNS recorded
and no `verified_fix` closes. A repo-wide grep confirmed nothing did the same
one level up: nothing enumerated more than one project root, nothing grouped
evidence BY project, and the only cross-project surface in the codebase --
`knowledge_center.py`'s remote broker -- is an add/search RPC against a shared
Linux DB path, not a miner (it never groups, never counts distinct projects,
and cannot run without a real remote server). So "the same root cause keeps
recurring across our projects, and one of them already fixed it" was a fact
nothing in this harness could compute. `dv_harness/cross_project_mining.py` is
that miner, and only that.

- **Reuse, not a parallel mechanism.** Failure identity is
  `evidence_db.signature_key()` -- the same hash the evidence store accumulates
  `occurrence_count` on and `repeated_unresolved_failure_patterns()` groups by,
  never a second definition of "the same failure". Evidence is read through the
  shared `MemoryStore.find()`. The Job/Engineering kinds are
  `capability_evolution.REPEAT_FAILURE_JOB_MEMORY_KIND` /
  `RESOLVING_ENGINEERING_MEMORY_KIND`, IMPORTED, so "only a gate-verified
  `verified_fix` closes a failure" stays one decision in one place; closure
  claim texts come from that module's own `failure_resolution_claims()` /
  `resolved_failure_claim_texts()`, so the join is the same exact-equality one.
  Within a project, independent observations are still counted by
  `_run_identity()`. The registry write goes through
  `storage._atomic_replace()` and the audit trail is `StateStore.event()`.
- **The unit of independence is the PROJECT.** `_run_identity()`'s discipline
  lifted one level: a project that recorded the same signature on forty runs is
  ONE cross-project observation, because forty runs of one environment are
  forty reports of one project's circumstances.
  `CROSS_PROJECT_MIN_PROJECTS = 2` distinct projects, for the same reason
  `memory_router.ORGANIZATIONAL_MIN_CONFIRMATIONS` and
  `REPEAT_FAILURE_MIN_OCCURRENCES` are 2.
- **That bar is enforced against fabrication, not merely stated.**
  `ProjectRegistry.register()` refuses a root whose memory store shares ANY
  `memory_id` with an already-registered one
  (`ProjectIdentityCollisionError`), and `mine_cross_project_patterns()`
  re-checks the same thing on the roots actually handed to it -- the registry
  file is editable text, so the guard cannot live only on the write path.
  Pointing the registry at one store twice under two names cannot manufacture a
  two-project consensus out of one project's audit trail.
- **The finding that only exists at this level** is `transferable_fix`: a
  gate-verified fix in project A for a signature project B still has open,
  carrying A's real `verified_fix` `memory_id` so the finding is citable rather
  than a summary. A bare `root_cause`/`debug_lesson` is an explanation, not a
  closure, and does not qualify.
- **A single-project pattern is REPORTED, never silently dropped** -- hiding it
  would make an empty cross-project result read as an absence of failures. So
  is the sample itself: fewer than two contributing stores returns
  `INSUFFICIENT_PROJECTS`, whose disclosure says the answer is about the SAMPLE,
  not about the projects.
- **It mints nothing.** Mining is a pure read: it writes no memory record of
  any tier, files no capability candidate, and creates no store in a root that
  has none (checked before a `MemoryStore` is ever constructed, since that
  constructor would bring one into existence). `promotion_readiness()` reports
  what an Organizational promotion would still need and performs none; the only
  route into that tier remains `memory_router.promote_to_organizational()`'s
  three gates plus `organizational_admission_gate()`, untouched here. The one
  write in the whole module is the registry file plus one `events.jsonl` event
  per registry change and per mining pass -- including a pass on which nothing
  qualified, which is itself citable evidence.

Reachable as `dv-harness cross-project register|unregister|list|status|mine`.
A refusal (including `ProjectIdentityCollisionError`) is printed as data and
exits 1 rather than raising; a completed `mine` exits 0 whatever it found,
because `INSUFFICIENT_PROJECTS` is an honest answer about the sample, not a
failure of the command.

Proven by `dv_harness_tests/test_cross_project_mining.py` (22 tests) against
MULTIPLE separately constructed real memory stores -- each project a real
`MemoryStore` populated through the real `memory_router.route_and_store()` with
the exact record shapes `engine._record_debug_attempt_job_memory()` and
`_promote_verified_fix_knowledge()` write, and real
`memory_vault.build_failure_signature()` signatures. Negative controls carry the
detection power: forty runs in one project are still not a cross-project
pattern, three retries against one commit are one run, an explanation is not a
closure, a byte-for-byte copy of a project is refused at registration AND
excluded at mine time, a bare directory neither gains a store nor pads the
count, and a byte-level snapshot proves no mined store was mutated. Nothing in
it runs a build, a regression or an LSF submission.

**Disclosed residual -- no production cross-project result exists, honestly.**
This repository is ONE project with ONE memory store; there is no second real
project here to mine, the same disclosure Environment Generation Mode already
makes about this repo having no RTL tree of its own. `production_status()`
computes that answer rather than claiming it, and
`test_this_repository_honestly_reports_no_production_cross_project_result`
asserts it against the real repo root. Synthesising a second "project" out of
this repo's own audit trail to manufacture a production-looking result is
exactly what `ProjectIdentityCollisionError` refuses.

**Second disclosed residual**: this has a CLI verb but no AUTOMATIC trigger --
no `run_stage()`/`advance()` call site invokes it, no graph node declares it,
and it is not on the dashboard. That is deliberate for now rather than
unfinished: auto-mining on a stage boundary would fire against a registry that
is empty in every real installation today and emit nothing but no-op events, and
registration is deliberately a human act so that "which projects agree" never
depends on where the harness happened to be run from. Federating the mine across
`knowledge_center.py`'s shared broker (rather than local roots) is likewise
deferred -- it needs a real remote server and could not be honestly tested here.



