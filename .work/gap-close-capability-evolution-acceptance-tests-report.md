# Stage-1 acceptance tests A–H, Stage-0/1 artifacts, CLAUDE.md consolidation

**Scope**: Stage 0 + Stage 1 of
`DV_Agent_Harness_L5_Research_Capability_Evolution_Master_Prompt_vLatest.md`
ONLY. No real external paper was ingested (that is Stage 2) and no
capability-evolution change was implemented in production code (that is Stage 3,
which needs `dv-harness approve --stage RESEARCH_CAPABILITY_EVOLUTION` first).
Repo root for every path below is `D:\DV\Task\DV_Agent_Harness_L5\v50`.

**Status: DONE.**

---

## 1. What this pass found already done, and did not rebuild

The four earlier build steps in this workflow had already landed
`research-ingestion`, `research-architect`, the routing front door, and the
research memory-governance extension — three of them as real commits (`7137f50`,
`ad518e5`, `6fe388b`, plus `ed7a546`), which I re-verified by reading the files
and running the tests rather than trusting the log. Six of the eight acceptance
tests (B, C, D, E, F, H) already had real, passing, named tests.

Two did not, exactly as the task predicted: **A** (ingestion end to end) and
**G** (prior-research comparison). G additionally had **no code at all** — the
card schema carries a `prior_research_link` $def and a seven-label relation enum,
but nothing anywhere compared one card against another.

One Stage-0 finding was already stale by the time I read it: the audit reported
`CLAUDE.md` as having zero research content. Commit `6e27a6c` had added a
"Research Front Door" section in the meantime. The real remaining gap in that
file was narrower — the **stage boundaries** — and that is what section 4 below
closes.

## 2. Acceptance tests A–H: present / passing, test by test

Every row names real test functions in real files. Command and output in §5.

| Test (master prompt §23) | Expected | Present | Covering test file | Test functions | Result |
|---|---|---|---|---|---|
| **A — Research Ingestion** | one paper → valid card, provenance, explicit limitations, claim classification, confidence, **no invented evidence** | **NEW this pass** | `dv_harness_tests/test_research_stage1_acceptance_a_g.py` | 12: `test_A_the_chain_produces_a_card_that_validates`, `…provenance_is_the_real_file_and_not_a_typed_string`, `…every_claim_and_result_carries_its_own_source_location`, `…limitations_are_explicit_and_use_the_closed_tag_vocabulary`, `…every_claim_is_classified_and_the_two_schema_rules_really_bind`, `…promoting_the_author_claim_to_a_fact_is_refused_by_the_real_schema`, `…confidence_uses_the_existing_inference_vocabulary`, `…no_invented_evidence`, `…the_no_invented_evidence_auditor_catches_a_fabricated_number`, `…the_no_invented_evidence_auditor_catches_a_fabricated_section`, `…the_search_basis_is_required_even_where_nothing_was_found`, `…ingestion_writes_only_under_research_and_the_harness_state_dir` | **PASS** |
| **B — Existing Capability Detection** | ENHANCE, not automatic ADD | prior step | `test_capability_evolution_research_architect.py` | 4: `test_B_overlapping_technique_produces_enhance_not_add`, `test_B_add_is_refused_even_when_the_agent_asks_for_it`, `test_B_add_is_reachable_only_from_a_conclusively_empty_search`, `test_B_missing_without_a_stated_enhance_reason_falls_back_to_experiment` | **PASS** |
| **C — Unknown** | UNKNOWN, not fabricated facts | prior step | `test_capability_evolution_research_architect.py` | 3: `test_C_insufficient_repository_evidence_produces_unknown_not_missing`, `test_C_unknown_is_reported_with_the_real_next_best_action`, `test_C_a_missing_claim_over_an_inconclusive_search_does_not_validate` | **PASS** |
| **D — Human Gate** | production source unchanged before approval | prior step | `test_capability_evolution_research_architect.py` | 2: `test_D_running_the_decision_logic_modifies_no_repo_file`, `test_D_everything_persisted_lands_under_the_project_state_dir` | **PASS** |
| **E — Deterministic Oracle** | no verification PASS from LLM reasoning alone | prior step | `test_capability_evolution_research_architect.py` | 4: `test_E_no_decision_vocabulary_can_be_read_as_a_verification_verdict`, `test_E_the_module_never_names_a_verification_verdict_at_all`, `test_E_decision_output_is_always_inside_its_own_closed_vocabulary`, `test_E_confidence_is_recomputed_never_believed` | **PASS** |
| **F — Future Short Invocation** | routes to ingestion → architect without replaying the master prompt | prior step | `test_research_intent_routing.py` | 4: `test_acceptance_f_canonical_request_routes_to_ingestion_then_architect`, `…every_routed_step_names_an_asset_that_really_exists`, `…through_the_real_cli_front_door`, `…natural_language_request_through_the_cli_needs_no_agent_name` | **PASS** |
| **G — Prior Research Comparison** | overlap / new / contradiction identified **and linked** | **NEW this pass (code + tests)** | `dv_harness_tests/test_research_stage1_acceptance_a_g.py` | 17: `test_G_the_card_store_is_read_from_real_filed_cards`, `…a_new_paper_against_the_whole_store_gets_a_status_and_a_link_each`, `…a_contradicting_metric_is_reported_as_CONTRADICTS_with_its_signal`, `…pure_overlap_without_a_metric_conflict_is_OVERLAPS`, `…a_superset_of_mechanisms_is_EXTENDS`, `…an_unrelated_paper_is_new_not_overlapping`, `…a_first_card_with_no_priors_is_new`, `…a_re_ingested_identical_document_is_flagged_as_not_independent`, `…a_card_stating_neither_mechanism_nor_domain_is_INSUFFICIENT_EVIDENCE`, `…a_document_s_own_declared_relation_outranks_derivation`, `…a_declared_contradiction_is_honored_even_with_no_metric_conflict`, `…every_link_validates_against_the_schema_s_own_link_shape`, `…the_relation_vocabulary_is_the_schema_s_and_not_a_second_copy`, `…comparison_never_edits_a_filed_card`, `…links_persist_to_working_memory_through_the_real_router`, `…the_link_memory_kind_is_an_existing_research_kind`, `…a_research_link_record_cannot_reach_engineering_memory` | **PASS** |
| **H — Memory Governance** | stored as evidence, never auto-promoted to Organizational truth | prior step | `test_research_memory_governance.py` | 4: `test_acceptance_h_fresh_card_cannot_reach_organizational_memory`, `…rejection_names_the_missing_authority`, `…a_self_written_approval_block_is_not_an_approval`, `…holds_for_every_research_evidence_kind` | **PASS** |

**8 / 8 present and passing.** `RESEARCH CAPABILITY INSTALLATION: PASS` (master
prompt section 24).

## 3. What Test A actually exercises (why it is not a mocked unit test)

The fixture writes a real 40-line synthetic preprint to disk, then runs the
chain `research-ingestion/SKILL.md` prescribes, in its own order:

1. `doc_extraction.build_research_evidence_card_skeleton()` — real sha256 of
   real bytes, `DOC-<12 hex>` derived from it, real `DocumentIndex` registration;
2. `doc_extraction.research_card_missing_fields()` — asserted to equal
   `RESEARCH_CARD_LLM_AUTHORED_FIELDS` exactly, i.e. the reader's real worklist;
3. the analytical half, written from the synthetic paper's actual text;
4. `doc_extraction.validate_research_evidence_card()` — the real jsonschema
   Draft 2020-12 validator with FormatChecker;
5. filing to `research/evidence_cards/paper_001.card.json`, then re-reading and
   re-validating what landed on disk.

**"No invented evidence" is checked, not asserted.** `invented_evidence()`
re-derives from the document's own bytes that (a) every `source_location.section`
on a claim or a quantitative result names a heading the document really has, and
(b) every number appearing in a `claim_text`, a `quantitative_results.value`, a
`context` or a `supporting_evidence` string is a number the document really
prints. It is held to two negative controls — a fabricated number and a
fabricated section — because an auditor nobody proved can fail is not evidence.

**The auditor caught a real defect on its first run**, in my own hand-written
card: `quantitative_results[1].value` was `"0"` for "excluded tests that changed
verdict", but section 5.2 of the paper prints *"No excluded test changed its
verdict"* and never prints a `0`. That is exactly the normalisation
`research-ingestion/SKILL.md` step 3 forbids ("exactly as printed, never
normalised"). The card now carries `"none"`, with a comment recording why.

Test A also fingerprints **every file** under `dv_harness/` and `.claude/` before
and after a full ingest and asserts zero bytes changed, and asserts that a
complete ingest writes only under `research/` and `.dv-harness/` — the same
discipline test D applies to the architect.

## 4. What Test G required building, and the REUSE decisions behind it

Test G had no code. `research-ingestion` **cannot** provide it: section 27
forbids that skill from looking at any other document while it writes a card,
and section 28 assigns cross-document synthesis to `research-architect`. So the
comparator was added as an **extension of `dv_harness/capability_evolution.py`**
(the architect's own module), not as a third research module.

`compare_evidence_cards(new_card, prior_card)` is a pure function — reads no
file, writes no file, calls no model, mutates neither card. Rule order, first
match wins, each rule recording what it matched on:

1. `INSUFFICIENT_EVIDENCE` when either card states neither `key_mechanisms` nor
   `verification_domain` (nothing to compare; `UNRELATED` would claim a
   comparison that did not happen — the same discipline test C enforces);
2. `OVERLAPS` on identical `document_sha256`, with the note flagging it as a
   **re-ingestion, not a second independent source** (section 28's "repeated
   vendor marketing is not convergence");
3. `CONTRADICTS` on any signal from `_contradiction_signals()` — a declared
   CONTRADICTS, a `contradictions[].against` naming the prior document by id or
   title, or **both cards reporting the same metric with different values**, the
   one contradiction two independently-written cards can establish without
   either mentioning the other;
4. whatever the new document itself declared, when it declared something;
5. `EXTENDS` (shared mechanisms are all of the prior card's, plus more) /
   `OVERLAPS` (mechanisms shared either way);
6. `OVERLAPS` on a shared verification domain with no shared mechanism;
7. `UNRELATED` otherwise.

Five REUSE decisions, each testable:

| Decision | Instead of | Held by |
|---|---|---|
| Relation vocabulary read from the card schema (`doc_extraction.prior_research_relations()`) | a private 7-tuple in `capability_evolution.py` | `test_G_the_relation_vocabulary_is_the_schema_s_and_not_a_second_copy` greps the module source for a module-level constant containing the enum — and **caught one**: my first draft had `_OVERLAP_RELATIONS = ("OVERLAPS","EXTENDS","SUPPORTS","SUPERSEDES")`, a partial second copy. It is now stated as the exclusion (`_NON_OVERLAP_RELATIONS`), so a relation added to the schema later cannot silently fall out of it. |
| The link is the schema's own `prior_research_link` shape | a private link dict | `test_G_every_link_validates_against_the_schema_s_own_link_shape` validates each link against that `$def` with jsonschema |
| Persisted with the EXISTING `research_claim` kind through `route_and_store()` | a new memory kind, or a direct tier write | `test_G_the_link_memory_kind_is_an_existing_research_kind`, `test_G_links_persist_to_working_memory_through_the_real_router` |
| WORKING_MEMORY asserted at the write site | trusting the router | the same guard `persist_candidate()` already carries; `test_G_a_research_link_record_cannot_reach_engineering_memory` re-checks test H's rule at this new write site rather than assuming it |
| The comparator never edits a card | writing architect-derived links into the card's `related_prior_research` | `test_G_comparison_never_edits_a_filed_card` sha256-checks every filed card before and after. `related_prior_research` records what THAT DOCUMENT asserts about other work (the schema says so); writing an architect's conclusion there would destroy the section-27 distinction. |

**`SUPPORTS` and `SUPERSEDES` are deliberately unreachable by derivation.**
Deciding that one document corroborates or replaces another is a reading
judgement, not something set intersection can establish. They appear only when a
document itself declares them (`test_G_a_document_s_own_declared_relation_outranks_derivation`).

**Test G's three words are three derived booleans, not a fourth vocabulary.**
`link_prior_research()` returns `has_overlap` / `has_contradiction` / `is_new`,
each a projection of the seven schema labels, so nothing here can disagree with a
card's own `related_prior_research` about what OVERLAPS means.

## 5. Files changed

| File | Change |
|---|---|
| `dv_harness/doc_extraction.py` | +1 function, `prior_research_relations()` — reads the card schema's own `prior_research_link.relation` enum, same pattern as `research_card_required_fields()`. Nothing existing touched. |
| `dv_harness/capability_evolution.py` | +1 section (~330 lines): `EVIDENCE_CARD_DIR`, `PRIOR_RESEARCH_LINK_MEMORY_KIND`, `_NON_OVERLAP_RELATIONS`, `prior_research_relations()`, `_norm_terms()`, `_norm_text()`, `_declared_relation()`, `_contradiction_signals()`, `compare_evidence_cards()`, `prior_research_link()`, `read_evidence_cards()`, `link_prior_research()`, `persist_prior_research_links()`. Nothing existing touched. |
| `dv_harness_tests/test_research_stage1_acceptance_a_g.py` | NEW, 29 tests (12 A, 17 G) |
| `research/current_harness_baseline.md` | NEW — the section-4 Stage-0 baseline (below) |
| `research/README.md` | corrected two stale claims: `research-architect` is now built, and `current_harness_baseline.md` is a **Stage 0** output (section 4), not a Stage 2 one as the file previously listed it |
| `CLAUDE.md` | +1 short section, "Research Stage Boundaries (2026-09-04)" |

**Not touched**, per this workflow's concurrency constraint: `dv_harness/engine.py`
and `dv_harness/stage_profile_report.py` both carry another workflow's
uncommitted changes (a stage-progress-display gap-close), and `.dv-harness/**`,
`.gitignore` and several `.work/*.md` files are likewise mid-flight elsewhere.
`git status` was checked on every file before editing; `CLAUDE.md`,
`research/README.md`, `doc_extraction.py` and `capability_evolution.py` were all
clean at HEAD when this pass began.

**The predicted collision happened, on `CLAUDE.md`.** Between that check and the
commit, a concurrent workflow appended 48 lines of its own to the same file (the
autonomous-blackboard-topic-refresh and atomic-`Blackboard.write()` sections).
`git diff` therefore showed two hunks. The hand-scoped patch technique was used
exactly as the task specifies: `git diff -- CLAUDE.md > patch`, trim to my own
hunk (`@@ -1221,3 @@`, the file tail), `git apply --cached --check` → clean, then
`git apply --cached`. The other workflow's 48 lines were left unstaged and
untouched, confirmed by `git diff --numstat CLAUDE.md` returning `48 0` after the
commit. Every other path was staged individually by name; no broad `git add` was
run at any point.

Commit: `b309300 research(stage-1): close acceptance tests A and G, and record
the Stage-0 baseline` — 6 files, +1573/-10, on branch
`gap-close/env-manifest-fact-sources` (never `main`/`master`).

## 6. `research/current_harness_baseline.md` (task item 2)

Generated from the five real Stage-0 audits, not a generic template. It carries
the section-4 column set (Capability / Status / Relevant Files / Owning Agent /
Owning Skill / Graph Node / Blackboard-State / Memory Layer / Evidence Mechanism
/ Known Limitation / Reuse Potential) across five tables — routing+agents+graph,
Blackboard/memory/evidence/confidence/inference, human gate + session + remote +
git governance, capability evolution, and the verification-domain mechanisms —
plus two sections section 4 explicitly asks for:

- **Documentation-vs-implementation mismatches** (six real ones, including that
  every `.dv-workflow/*.csv` a planner skill declares exists only as a blank
  `.claude/templates/` header with no generator anywhere, and that
  `self_tuning.py` is genuinely wired at three points while tuning zero real gate
  behaviour — no non-test caller of `get_param()` exists).
- **A REUSE / EXTEND / ADD ledger** for every section-2.2 mechanism, with the
  evidence for each call.

Counts in it were **re-measured for the document**, not quoted from the audits:
41 graph nodes / 58 edges and 7 declared routes, 36 `STAGE_GATES` stages, 5
memory levels, 322 `SKILL.md` files (132 directly under `CORE/`), 24 agent
profiles, 14 `CREATE TABLE`s in `evidence_db.py`. Several differ from numbers the
audits recorded hours earlier the same day (28 stages, 95-line `blackboard.py`,
150+ CORE skills) — that is concurrent work in this repo, and the baseline says
so rather than picking one silently.

## 7. `CLAUDE.md` (task item 3)

`git status`/`git log` were checked first: the file was **clean at HEAD**
(`1836b0b`), with the research front door added by `6e27a6c` earlier the same
day. So the pre-existing Stage-0 finding ("zero research content in CLAUDE.md")
was already closed; the real remaining gap was the stage boundary. (It did not
stay clean — see §5 for the concurrent edit that landed before the commit, and
how only my own hunk was staged.)

The addition is short and points outward, per the Methodology Consolidation
Rule: the capability is permanent and proven by A–H; **Stage 2 (analyzing real
external documents) starts only when a human asks**, and **Stage 3 (implementing
an approved change) requires a separate explicit
`dv-harness approve --stage RESEARCH_CAPABILITY_EVOLUTION`** — a strong card, a
confident synthesis or a HIGH-confidence candidate is never that approval, and
`main`/`master` is still reached only through the gh/PR-Only policy. Detail is
pointed at (`research/README.md`, `research/current_harness_baseline.md`, the
SKILL/agent files, `capability_evolution.py`), not inlined.

## 8. Test evidence (real commands, real output)

### The new acceptance suite

```
$ cd v50 && python -m pytest dv_harness_tests/test_research_stage1_acceptance_a_g.py -q
29 passed in 16.10s
```

### All five research suites together (A–H in one run), after every edit

```
$ python -m pytest dv_harness_tests/test_research_evidence_card.py \
    dv_harness_tests/test_capability_evolution_research_architect.py \
    dv_harness_tests/test_research_intent_routing.py \
    dv_harness_tests/test_research_memory_governance.py \
    dv_harness_tests/test_research_stage1_acceptance_a_g.py -q
225 passed in 22.60s
```

### Doc-holding suites re-run after the CLAUDE.md / README edits

```
$ python -m pytest dv_harness_tests/test_research_evidence_card.py \
    dv_harness_tests/test_research_intent_routing.py -q
122 passed in 23.02s
```

### Full project suite

```
$ python -u -m pytest dv_harness_tests/ -q -rf -p no:cacheprovider -n 8 --dist loadfile
16 failed, 4098 passed, 6 errors in 2308.02s (0:38:28)
```

**Why `-n 8 --dist loadfile` and not a plain serial run.** A serial
`python -m pytest dv_harness_tests/ -q` was started first and reached only **8%
in ~35 minutes** — 2-3 other workflows in this same repo were running their own
suites, and, more importantly, were *committing to `dv_harness/` while it ran*
(`982b918`, `48c1251` both landed mid-run). A 7-hour serial run whose tree
changes underneath it does not measure anything. `--dist loadfile` keeps every
test file whole on one worker, so intra-file ordering is preserved; it is not a
free substitute for serial, which is exactly why every failure below was then
**re-run serially**.

### No baseline "before" run — stated rather than fudged

The task allows a before/after comparison "if you can determine the prior
baseline". I could not honestly produce one. The working tree carries in-flight
uncommitted work from several other workflows (`engine.py`, `cli.py`,
`memory.py`, `memory_dedup.py`, `memory_router.py`, `connectivity.py`,
`amba_fabric_discovery.py`, `stage_profile_report.py`, plus five untracked new
test files), so "the tree without my change" is not a state I can create without
reverting other people's live work, and a clean HEAD worktree would differ from
today's tree for reasons that have nothing to do with this pass. What is
reported instead is **today's real full-suite result plus a per-failure serial
re-verification**, which answers the actual question — *did this pass regress
anything* — more directly than a count comparison would.

### Every failure attributed, by re-running it serially

Two serial re-runs covering all seven failing files:

```
$ python -u -m pytest dv_harness_tests/test_amba_vip_bind_plan.py \
    dv_harness_tests/test_dashboard_interactive.py dv_harness_tests/test_justfile.py \
    dv_harness_tests/test_doc_citation_check.py \
    dv_harness_tests/test_rca_multi_agent_fanout.py -q -rf
1 failed, 169 passed in 293.54s (0:04:53)

$ python -u -m pytest dv_harness_tests/test_engine_gates_and_routing.py \
    dv_harness_tests/test_cli_pueue.py dv_harness_tests/test_pueue_client.py -q -rfE
5 failed, 270 passed, 6 errors in 1329.00s (0:22:09)
```

| Failure(s) in the parallel run | Reproduces serially? | Attribution |
|---|---|---|
| `test_amba_vip_bind_plan.py` ×4 | **No — all pass** | The file is **untracked** (`git status` → `??`): a concurrent AMBA workflow's in-flight new test, alongside its uncommitted `dv_harness/amba_fabric_discovery.py`. Not this pass's, and not even a committed file yet. |
| `test_dashboard_interactive.py::test_start_loop_true_advances_through_multiple_stages_in_background` | **No — passes** | Background-loop timing under 8 workers. |
| `test_doc_citation_check.py` ×2 | **No — both pass** | Memory-doc citation drift against the concurrently-modified `memory.py`/`memory_dedup.py`/`memory_router.py`; transient under parallel execution. |
| `test_rca_multi_agent_fanout.py::test_real_issue_triage_dispatches_the_rca_fanout_end_to_end` | **No — passes** | A wall-clock timing assertion; contention artifact. |
| `test_engine_gates_and_routing.py` ×2 (`test_constraint_cli_add_list_remove_round_trip` subprocess timeout, `test_self_audit_against_real_repo_reports_real_current_findings`) | **No — both pass** | One was a `subprocess.TimeoutExpired` under load; the other audits the real repo, which other workflows were mutating mid-run. |
| `test_justfile.py::TestMemoryRecipes::test_every_memory_cli_subcommand_has_a_recipe` | **Yes** | A concurrent workflow's **staged** `dv_harness/cli.py` (`git status` → `M ` in the index) adds memory subcommands whose `justfile` recipes are not written yet. This pass touched neither `cli.py` nor the `justfile`; my commit's six files are listed in §5. |
| `test_cli_pueue.py` ×5 + `test_pueue_client.py::TestRealPueueIntegration` ×6 errors | **Yes** | All eleven share one root cause, printed verbatim by the fixture: `AssertionError: real pueued did not come up`. `pueued` is on PATH (`/c/Users/peter.lin/bin/pueued`) but the daemon does not start in this environment. An external task-queue binary, unreachable from anything in this pass. |

**Regression verdict for this pass: none.**
- Zero failures in any research or capability-evolution test — all 225 pass, in
  the full-suite run and standalone.
- **No failing test file references `capability_evolution`, `doc_extraction`, or
  `research` at all** (checked with `grep -ln` over all seven files → no match).
- Of the 22 failures/errors, **8 do not reproduce serially** (parallel-execution
  artifacts), **1** is a concurrent workflow's staged `cli.py` vs `justfile`
  mismatch, and **11** are one absent external daemon.

## 9. Honest limits

- **Nothing here has been run against a real external paper.** Test A ingests a
  synthetic preprint written for this test. That is deliberate: ingesting real
  literature is Stage 2, which the master prompt's First-Run Control Instruction
  (sections 57 / 82) forbids starting before these tests pass. What test A
  proves is that the chain works end to end on a real file with real bytes, not
  that any real paper has been read.
- **`invented_evidence()` is a mechanical check, not a proof of honesty.** It
  catches a citation to a section that does not exist and a number the document
  never prints. A reader can still mis-characterise a passage that does exist;
  no code in this repo can catch that.
- **The comparator is deterministic and therefore conservative.** It matches
  mechanism and domain strings after case/whitespace normalisation only — no
  synonym handling, no embeddings. Two cards describing the same mechanism under
  different names come back `UNRELATED`. That is a false negative by design
  (a missed link is visible and fixable; a fabricated link is not), and it is
  why a document's own declared relation always outranks derivation.
- **Still REACHED, not WIRED.** No graph node declares `research-route`;
  `ROSTER.md` still correctly records `research-architect` as `NOT_DISPATCHED`.
  Nothing in this pass changed that, and nothing should until a Stage-2 need for
  a stage-owning path is real.
- **Nothing was promoted to Organizational Memory**, and the two write sites
  this pass touched (`persist_candidate`, `persist_prior_research_links`) both
  assert WORKING_MEMORY and raise otherwise.
- **`self_tuning.py` still tunes zero real gate behaviour.** The baseline records
  it; closing it is out of this workflow's scope.
- **The full-suite number is a parallel run, and the tree was moving.** 4098
  passed / 16 failed / 6 errors is a real measurement of a real tree, but that
  tree contained several other workflows' uncommitted work and gained two
  commits while the first (abandoned) serial run was in flight. Every failure
  was re-run serially and attributed above; none belongs to this pass. Anyone
  re-running this on a quiet tree should expect the 8 parallel artifacts to
  vanish and the pueue eleven to persist until `pueued` starts here.

**DONE.**
