# Execution / Remote EDA / Regression / RCA — Detailed Task-Scoped Governance

Moved out of CLAUDE.md during **M4.6 — CLAUDE Context Normalization**. Registered as `id: EXECUTION_REMOTE_REGRESSION_RCA`, `load_policy: TASK_SCOPED`. Sections preserved verbatim; only residency changed.

Covers: remote/LSF execution, build/sim-script mechanisms, waveform/FSDB, regression loop control, convergence/plateau detection, and root-cause analysis support mechanisms.

---

<!-- S037: moved verbatim from CLAUDE.md original lines 1177-1261 (M4.6 CLAUDE Context Normalization) -->
## System Build & Smoke Proof (2026-09-06)

Spec section 206's smoke-proof ladder is now DRIVEN, and the system MERGE COLLISION check it
opens with is real. The gap was total: `grep -rn "smoke_proof\|SMOKE_PROOF\|system_smoke"
--include=*.py .` matched NOTHING, so no code anywhere executed
Build → Elaborate → Boot/Reset/Init → Shared-Resource-Access → One-Subsystem →
Two-Subsystem-Interaction → One-End-to-End-Scenario → WAVE=1/fsdbreport → Scoreboard/Assertion →
SYSTEM_READY. Two nearby mechanisms are deliberately NOT this and were not extended into it:
`system_readiness.derive_system_readiness()` is a static metadata ROLLUP and says so in its own
docstring ("Build integration at Phase 1 is a question about INPUTS, not about a build: no
System-Level filelist exists to compile"), and `uvm_structural_lint.py` lints ONE environment —
a duplicate class or an identically-named package across TWO subsystem environments is invisible
to a per-environment lint by construction, which is why its own docstring lists "duplicate
definitions" as not implemented.

`dv_harness/system_build_proof.py` is both halves.

**The merge check (`analyze_system_merge()`) is REAL here and needs no simulator.** It parses the
merged source set with the SAME verible front end via `uvm_structural_lint.parse_uvm_file()` —
there is no second SystemVerilog parser — and decides five things section 206 names:
`DUPLICATE_PACKAGE_DECLARATION`, `DUPLICATE_TYPE_DEFINITION` (class/interface/module),
`FACTORY_TYPE_NAME_COLLISION` (the UVM factory keys on the registered STRING, so two differently
-named classes registering one name collide with no duplicate definition anywhere),
`CONFIG_DB_SET_SCOPE_COLLISION` and `VIRTUAL_INTERFACE_CONFLICT`. Two additions were made to
`uvm_structural_lint.py` to serve it rather than duplicate it: `UvmFileInfo.top_declarations`
(package/interface/module names off the same parse) and the now-public
`config_db_call_sites()`, which `_config_db_sites()` was refactored to use, so there is one place
that knows how a `uvm_config_db` call is shaped. Sources come from the REAL registry through
`subsystem_source_sets()` → `environment_mode_router.read_registered_subsystem_entries()`.

**Deliberately bounded, and stated rather than implied closed.** A config_db collision is reported
ONLY when both `set`s are rooted in the GLOBAL context (`null`/`uvm_root::get()`/`uvm_top`) and
their `inst_name` globs overlap. A `set(this, ...)` resolves to wherever that component is
instantiated, which a parse cannot know, so it is never reported — ERROR stays reserved for what
the sources prove. A run-time-built scope is an INFO finding saying it was excluded, never
silently dropped. Two colliding `set`s inside ONE subsystem are not reported: that environment
already worked standalone and this check is about what the MERGE breaks. Duplicate VIP and address
conflicts are NOT re-implemented here — they are SYS-9..SYS-14 / SYS-28 and already have real
mechanisms.

**The ladder (`run_system_smoke_proof()`) calls existing mechanisms, or says NOT_AVAILABLE.**
ELABORATE is `connectivity.run_gate1_elaboration_check()`; BOOT_RESET_INIT is
`connectivity.evaluate_zero_time_connectivity()` (or `run_gate2_against_live_simv()`'s honest
NOT_AVAILABLE); SHARED_RESOURCE_ACCESS is `system_resource_inventory.real_cross_subsystem_findings()`
— the same Track-B front door the two real gate scripts and the SoC composer already cross-check
against, and it really runs here; ONE_SUBSYSTEM / TWO_SUBSYSTEM_INTERACTION are
`connectivity.evaluate_transaction_activity_status()` (PENDING until a real pattern completes,
never FAIL-by-absence), the second additionally requiring live monitors in ≥2 subsystems;
WAVE_FSDBREPORT is `fsdb_report.run_fsdbreport()` + `parse_fsdbreport_output()` over an fsdb the
caller ALREADY HAS — it never enables dumping, which would need the Waveform Dump User Gate;
SCOREBOARD_ASSERTION reads the REAL `evidence_db` `normalized_evidence` rows with
`golden_scenario.PASS_VERDICTS`, not a second notion of "clean". END_TO_END_SCENARIO is
NOT_AVAILABLE by default naming the real boundary: `cross_subsystem_scenarios()` raises
NotImplementedError on purpose (No Golden-Reference Content Mining) and SYS-40 stops for human
approval, so this harness cannot generate one to run.

`SYSTEM_READY` requires EVERY rung PASS; anything NOT_AVAILABLE/PENDING is `SMOKE_NOT_PROVEN`
(GF-AT-28: UNKNOWN never becomes READY automatically), and a FAIL is `SMOKE_FAIL` which HALTS the
ladder — the rungs after it are NOT_YET_RUN, section 209's `SMOKE_FAIL → TRIAGE` edge. A
composition with fewer than two source sets, or none on disk, is NOT_AVAILABLE, never a clean
merge of nothing (this repo's own subsystem registry is legitimately EMPTY).
`dv-harness system-smoke-proof [--merge-only] [--json]` and
`python -m dv_harness.system_build_proof` share one `execute_verb`; exit 0 SYSTEM_READY,
1 SMOKE_FAIL, 2 SMOKE_NOT_PROVEN.

**It generates nothing and arbitrates nothing**, and both are held by AST tests over the module
itself rather than by prose: it calls no composer generation entry point, writes no file, submits
no job, and picks no winner between two ACTIVE drivers — a DRIVER_CONFLICT FAILS the rung carrying
`human_arbitration_required` and SYS-12's preferred model as text for the human who must decide.

Proven by `dv_harness_tests/test_system_build_proof.py` (43 tests): a synthetic REGISTERED
two-subsystem project with real parseable UVM sources merges clean, then every rule is driven by
MUTATING that clean fixture ONE defect at a time (including a real injected duplicate global
config_db path whose two virtual interface types differ, which the check catches); the REAL
Track-B analysis really finds an injected active-driver conflict and STOPS the ladder; the full
ladder is driven to a real SYSTEM_READY through a real elaboration subprocess, a real
`fsdbreport` binary on disk, and a real DuckDB EvidenceStore row, and withdrawing exactly one
rung's evidence drops it back out of SYSTEM_READY. It is also run over the environments this
project's generator really produced (`examples/generated_pcie_uvm_env`,
`examples/generated_usb_real_evidence_v12`), where it finds exactly one collision — both
generators emit `module tb_top` — which is a genuine system-merge defect, and reports the
composition Track A actually performs (each subsystem's env/tests plus ONE composed system top)
as clean.



<!-- S052: moved verbatim from CLAUDE.md original lines 2229-2283 (M4.6 CLAUDE Context Normalization) -->
## Question-Queue Digest: Auto-Fired at Regression-Cycle Boundaries (2026-09-05)

The 3-tier ask-a-human queue (`dv_harness/question_queue.py`) batches every
never-yet-digested OPEN/ASSUMED question into one digest, and computes the 4
tracking metrics (self-resolve rate against its 90% target,
blocking-questions/week, repeat-question-rate, assumption-overturn-rate). Both
`build_digest()` and `compute_metrics()` were real, correct and individually
tested — and DORMANT. A repo-wide grep found each had exactly ONE caller: the
hand-typed `dv-harness question-queue digest` / `dv-harness question-queue
status` verbs. `engine.py` called neither, no CI job or cron named either, and
`build_digest()`'s own docstring said so ("not wired into engine.py itself in
this change"). So an unattended `loop()` run batched nothing for a human to
answer and recorded none of the 4 metrics — the same PARTIALLY_WIRED shape the
Methodology Consolidation Rule warns about.

`engine.DVHarness._emit_question_digest_at_stage_boundary()` closes it from
`advance()` — the single canonical "the current stage completed successfully,
move on" transition, which `loop()` delegates to on every PASS and
`commands.cmd_advance()` (`dv-harness next`) calls directly. Deliberately NOT
`set_stage()`/`human_redirect()`: those also fire on human reroutes and on
`loop()`'s FAIL-edge routing, which are not "a stage completed" boundaries and
would emit a digest in the middle of a failure recovery.

- Still never real-time. Only `question_queue.DIGEST_BOUNDARY_STAGES`
  (`REGRESSION_MONITOR`, `COVERAGE_CLOSURE`, `RE_AUDIT`, `SIGNOFF`) do any work;
  every ordinary stage transition leaves the queue completely untouched and
  does not even load it. Part B's "batched into a daily/end-of-run digest,
  never real-time pings" is unchanged — what changed is that the batch now
  happens without a human remembering to type the verb.
- One `QUESTION_QUEUE_DIGEST` event per boundary crossing in
  `.dv-harness/events.jsonl`, carrying `emitted`/`batch_id`/`question_count`/
  per-owner counts AND the full metrics dict. It is recorded on EVERY crossing,
  including `emitted: false` — a metrics series with datapoints only on the
  cycles that happened to have pending questions is not a series, and "this
  cycle had nothing to escalate" is itself citable evidence.
- Best-effort, mirroring `_file_waveform_dump_scope_question()`: an unreadable
  queue records `QUESTION_QUEUE_DIGEST_FAILED` and never turns a completed
  stage transition into a crash.
- It files and batches; it never ANSWERS. Only `answer_question()`, i.e. a
  human, writes a decision — the human checkpoint is unchanged.

Proven against a real `QuestionQueueStore` on disk and the real shipped
`main_graph.json` (never a mock of either), including a real gate-verified
`run_stage()` PASS followed by the same `advance()` the loop calls, by
`dv_harness_tests/test_question_queue_digest_auto_trigger.py`.

**Disclosed residual**: this is the `stage_boundary` trigger only. The
`scheduled` trigger (a daily cadence for a caller that polls without knowing
the stage) still has no scheduler in this repo — no cron, systemd timer or
Windows scheduled task names it, and the CI workflow deliberately does not,
since a fresh CI checkout carries no question store and would only ever record
an empty no-op. A project wanting the daily cadence runs `dv-harness
question-queue digest --trigger scheduled` from its own scheduler.



<!-- S053: moved verbatim from CLAUDE.md original lines 2284-2399 (M4.6 CLAUDE Context Normalization) -->
## Cross-Loop Coupling: Repeated Failure -> Auto-Filed Capability Candidate (2026-09-05)

Three loops in this harness were each individually real and firing — the
Verification Closure Loop (`engine.run_stage()`'s gates), the Project Learning
Loop (`memory_router`'s tier promotions) and the Capability Evolution Loop
(`capability_evolution.py`'s 11-state machine, §70) — and the EDGE between the
first and the third did not exist. A repo-wide grep confirmed
`router.resolve_intent()` (the research route added with `dv-harness research`)
has no caller anywhere in `engine.py`, so the Capability Evolution Loop was
reachable ONLY by a human typing `dv-harness research <doc>`. The same real
failure could recur across independent runs forever, be recorded faithfully in
Job Memory every single time, and never once raise a question about the
harness's own capability. That is the PARTIALLY_WIRED shape the Methodology
Consolidation Rule warns about, one level up: not an unwired module, but two
wired loops with no edge between them.

`engine.DVHarness._file_capability_evolution_candidates_from_repeated_failures()`
closes the DISCOVERY half. It is called immediately after
`_record_debug_attempt_job_memory()` — the one place in `engine.py` a real
`kind="job_failure"` record carrying a real `memory_vault.build_failure_signature()`
dict reaches Job Memory — so the coupling reads evidence the closure loop wrote
one line earlier, on the real autonomous path.

**Scope, precisely (three-loop gap-close review, 2026-09-05):** the filing
call site is `run_stage()`'s FAILURE_RECOVERY/RE_AUDIT FAIL/PARTIAL branch
only. `lsf_client._write_job_tier_memory_on_terminal_reconcile()` also writes
real `kind="job_failure"` records (on a real UVM_ERROR/UVM_FATAL/abnormal-
termination signal reconciled from LSF) — those contribute as EVIDENCE to
`repeated_unresolved_failure_patterns()`'s pattern-matching once two
independent runs exist, but do not themselves trigger the auto-file check.
A project whose failures arrive only via LSF reconcile, with `run_stage()`
never reaching a FAILURE_RECOVERY/RE_AUDIT FAIL/PARTIAL for the same
pattern, never fires the coupling on its own.

- **The threshold is evidence-based and conservative.** `capability_evolution.
  repeated_unresolved_failure_patterns()` groups Job Memory `job_failure`
  records by `evidence_db.signature_key()` (the SAME stable hash the evidence
  store already accumulates `occurrence_count` on — never a second definition of
  "the same failure") and fires at `REPEAT_FAILURE_MIN_OCCURRENCES = 2`
  INDEPENDENT runs. Independence is the run (`job_id`, else `git_sha`) and
  nothing else: three retries of one stage against one commit are ONE
  observation, matching `ORGANIZATIONAL_MIN_CONFIRMATIONS`'s own "not the same
  run reported twice". A record carrying neither identity contributes ZERO
  independent runs rather than one each — otherwise a single bad session could
  manufacture its own capability proposal.
- **UNRESOLVED means a gate-verified fix is absent**, not that nobody wrote an
  explanation. Only `kind="verified_fix"` closes a pattern, because
  `engine._promote_verified_fix_knowledge()` writes it exactly once, on an
  RE_AUDIT verdict whose `fix_effectiveness_gate` AND
  `fix_regression_non_regression_gate` both cleared. A bare `root_cause` or
  `debug_lesson` record is an explanation, not a closure. The join is exact
  equality on normalized claim text (the signature's `symptom`/`root_cause_hint`
  against the fix record's `root_cause`/`symptoms`), never fuzzy — both sides
  really are sourced from the same Blackboard `findings.last_report` evidence on
  the real path, and a fuzzy join would silently suppress real candidates, which
  is the more expensive error of the two.
- **DISCOVERY is automated. Nothing else is, and the wall is structural.** An
  auto-filed candidate is filed at DISCOVERED and can reach no further state,
  for three independent reasons: (1)
  `file_repeated_failure_candidate()` never calls `transition()` and refuses to
  persist anything not at DISCOVERED; (2) it performed NO repository search and
  says so — all six `existing_*` slots carry `search_conclusive: false` with an
  honest `search_basis` quoting that question's real next-best-action out of the
  existing `RESEARCH_GAP_ACTION_CATALOG` — so `derive_overlap_status()` returns
  UNKNOWN, `decide_recommendation()` returns UNKNOWN, and the candidate schema's
  own `allOf` then PINS `current_status` to
  DISCOVERED/EVIDENCE_GATHERING/REJECTED. Reaching PROPOSED requires six
  conclusive searches only a real `research-architect` pass can produce; (3)
  every gate above that is untouched — `assert_legal_transition()`,
  `assert_human_approval()`'s real `ControlPlane` check,
  `HumanApprovalRequiredError`, `ProductionWriteNotAuthorizedError`. Not one
  line of the human-approval boundary was weakened to build this.
- **A candidate a human has already moved on is never dragged back.** The
  content-derived `candidate_id` means a recurrence in a later cycle lands on the
  SAME record and accumulates evidence; if that record has left DISCOVERED, the
  auto-filer reports `ALREADY_BEYOND_DISCOVERED` and writes nothing. Unchanged
  evidence reports `ALREADY_ON_FILE_UNCHANGED` and writes nothing, so a failing
  stage retrying does not append a duplicate Working Memory audit record per
  attempt.
- **Reuse, not parallel infrastructure**: evidence read through the shared
  `MemoryStore.find()`; the candidate assembled by the existing
  `build_candidate()` (so the recommendation is DERIVED and the confidence is
  recomputed through the real `inference.score_confidence()`, never
  self-reported) and written by the existing `persist_candidate()`, landing on
  the one `capability_evolution_candidates` Blackboard topic and the one Working
  Memory audit trail every other candidate uses. `persist_candidate()`'s
  WORKING_MEMORY assertion still holds: one project's repeated failure is not
  verified engineering knowledge.
- Best-effort, mirroring every sibling `_promote_*`/`_record_*` method: a
  capability-evolution bookkeeping failure records
  `CAPABILITY_EVOLUTION_AUTO_DISCOVERY_FAILED` and never turns an
  already-computed stage result into a crash. Every outcome, including "no
  pattern qualified", is one `CAPABILITY_EVOLUTION_AUTO_DISCOVERY` event in
  `.dv-harness/events.jsonl` — a run on which nothing qualified is itself
  citable evidence.

Proven end to end — two real `run_stage()` calls that do not close, against two
different commits, writing two real Job Memory records through the real router,
producing a real candidate on the real Blackboard with those two real
`memory_id`s as its evidence, with no human involved and no approval minted — by
`dv_harness_tests/test_capability_evolution_auto_discovery.py` (23 tests),
which also holds the boundary: PROPOSED is refused, every skipped governance
state is refused, and both `HumanApprovalRequiredError` and
`ProductionWriteNotAuthorizedError` still fire on an auto-filed candidate.

**Disclosed residual**: this closes the AUTOMATIC-DISCOVERY half of the
coupling and only that half. The auto-filed candidate parks at DISCOVERED with
UNKNOWN overlap and UNKNOWN recommendation until a human runs
`dv-harness research` (or an equivalent `research-architect` pass) to perform
the six current-L5 searches; nothing in the engine performs them, and
`.claude/agents/ROSTER.md` correctly still records `research-architect` as
`NOT_DISPATCHED` — no graph node declares `research-route`. What changed is that
the loop now RAISES the question from real repeated evidence instead of waiting
for a human to notice the pattern.



<!-- S054: moved verbatim from CLAUDE.md original lines 2400-2502 (M4.6 CLAUDE Context Normalization) -->
## Harness-to-Remote-Agent-Path Deployment: `dv-harness harness-deploy` (2026-09-05)

`docs/workflow/USAGE_MULTI_USER_SAFETY.md:16-19` records as 固化 standing policy that "every
harness update must sync to `/home/svcacct/AI/Agent`, and every confirmed
gap/lesson must be distilled into a permanent skill/capability and written back
to `/home/svcacct/AI/DB`." The Knowledge Center half has been real and wired
since `dv_harness/knowledge_center.py`. The CODEBASE half was policy with no
mechanism, confirmed by direct search on 2026-09-05: `cli.py` had no
`deploy`/`harness-sync`/`push-remote` verb (only `memory sync`, a different
subsystem); repo-wide search for `deploy_harness`/`harness_deploy`/
`push_harness`/`sync_harness` returned zero hits; `justfile:27` flags "whether
dv_harness itself is deployed on the Linux server" as explicitly UNCONFIRMED;
and every `.work/*.md` report describing a sync narrates a manual, ad hoc
file-by-file copy an agent performed by hand that session, sometimes explicitly
skipped. `dv_harness/harness_deploy.py` is that mechanism.

**What "the harness" is, is DATA**: `dv_harness/harness_deploy.manifest.json`
(same policy-as-data shape as `context_budget.policy.json`) declares `include`
(`dv_harness/`, `dv_harness_tests/`, `tools/`, `.claude/skills`, `.claude/agents`,
`.claude/workflows`, `.claude/hooks`, `CLAUDE.md`, `pyproject.toml`, `justfile`),
`exclude` (`.dv-harness/` per-project RUNTIME state above all — one user's
`state.json`/`events.jsonl`/memory/evidence DB pushed over the shared tree would
clobber everyone else's, which is `docs/workflow/USAGE_MULTI_USER_SAFETY.md`'s own "never share
a `--project-root`" rule applied to the sync direction) and `never_sync`. Extend
the JSON for a project's own layout, never the Python.

**Nothing here re-derives hash math or transport.** The diff engine is the real,
tested `tools/remote/source_identity.py` (`three_way_diff()`/
`aggregate_source_id()`) — the same primitive `server_sync_identity_gate.py`
already uses to VERIFY PC-vs-server identity, used here to COMPUTE A PUSH DELTA.
The remote manifest arrives through the same real-captured-transcript convention
that gate established (`_remote_transcript.py`'s REMOTE_HOST=/EXIT_CODE=/STATUS=
markers over a real `remote_exec.py "md5sum ..."` stdout). Transport is
`remote_hop.py`'s already-documented tar → `--put` → `tar xzf` pattern, narrowed
to the diff set instead of the whole tree. The audit record is
`StateStore.event()` — one `HARNESS_DEPLOY_SYNC` entry in the same
`.dv-harness/events.jsonl` `dv-harness audit` already reads, never a second
parallel audit file.

**Three safety properties, each enforced in code and each tested:**
1. **Never blind-overwrite.** The push set is `local_only | different` ONLY.
   `remote_only` files are surfaced as a required human decision (exit code 3)
   and never deleted — server-side drift could be a legitimate hotfix somebody
   made under deadline or an accidental leftover, and this tool has no evidence
   to tell which.
2. **Never ship a credential.** `never_sync` RAISES (`SecretPathRefusedError`)
   rather than silently skipping. Not hypothetical: `replay.ps1` — the real,
   gitignored (`.gitignore:11`), untracked local credential script the Remote
   Linux Execution amendment above describes — sits in this checkout's root, and
   the destination is a SHARED multi-user path. A quietly-dropped file teaches
   the operator nothing and leaves the bad include glob in place.
3. **Never reach the network by accident.** `plan` makes ZERO network calls by
   construction: the remote side is either a local `--target-root` directory or
   an already-captured transcript file. `apply --target-root` performs real
   copies into a local/staging directory. The relay path builds the tarball and
   PRINTS the `remote_exec.py` sequence unless `--execute` is passed, and only
   ever names `remote_exec.py` — never `remote_relay.py`, per the standing rule
   above. That default is why the whole tool was built, wired and tested under a
   LOCAL_ANALYSIS declaration without ever touching the live server.

**CRLF vs LF is handled, and it is load-bearing, not cosmetic.** This checkout's
`core.autocrlf` is `true`, so the Windows working copy holds CRLF while a
`git clone`-populated `/home/svcacct/AI/Agent` holds LF — verified on this
checkout: `dv_harness/engine.py` hashes to `020fb26f...` as CRLF and
`a14df5e9...` as LF. A naive md5 diff would therefore report EVERY text file as
drifted on every plan, forever, re-push the whole harness each run, and never
once reach `in_sync` — a diff that is always maximal is not a diff. Measured
against the real 993-file tree: 204 files of phantom drift.
`classify_line_ending_only_differences()` compares the remote md5 (all a
transcript carries) against BOTH line-ending renderings of the local bytes, so
it needs no remote content and works on the transcript path that matters against
the real server. A genuine content change that ALSO crosses a line-ending
boundary matches neither rendering and stays in `push`; a binary file (NUL-byte
detected, the same heuristic git uses) is never normalized. `--strict-line-endings`
asks for the raw byte diff. The two SOURCE_IDs stay honestly UNEQUAL in this case
— they aggregate the raw md5s and the raw bytes really do differ — so
`in_sync: true` beside two differing SOURCE_IDs is the correct reading, and
`line_ending_only_count` in the same payload is why.

An absent `--target-root` is a refusal, not an empty remote: a typo'd path must
never read as "the target has nothing" and push the whole harness somewhere
wrong. A first-ever deployment is DECLARED with `--assume-remote-empty`, never
inferred. A nonzero-exit or marker-less remote transcript is likewise a refusal
rather than a short manifest that would read as "the server is missing
everything".

Verbs: `dv-harness harness-deploy manifest [--print-md5sum-command]` (resolved
file set + local SOURCE_ID, no remote side needed), `... plan` (exit 0 in sync /
1 work to push / 3 server-only files need a human), `... apply`. Proven against
this real checkout — 993 real files applied to a synthetic target, re-plan
reporting `in_sync` with matching SOURCE_IDs, an incremental single-file delta,
and the real 3-command transport sequence produced with `executed: false` — by
`dv_harness_tests/test_harness_deploy.py`.

**Disclosed residual**: this closes the MECHANISM, not an executed deployment.
No sync to the live `/home/svcacct/AI/Agent` has been performed by this tool;
doing so is REMOTE_EXECUTION and requires a fresh SSH/Remote Transport Connection
Intake confirmation per the gate above. Nothing calls `harness-deploy`
automatically either — there is no post-commit hook or CI step invoking it, so
"every harness update must sync" is still a human-run verb, not an engine-fired
one. It is a REACHED capability (a real CLI caller exists), not a WIRED one.



<!-- S055: moved verbatim from CLAUDE.md original lines 2503-2615 (M4.6 CLAUDE Context Normalization) -->
## Controlled Experiments Are Executed, Not Attested (2026-09-05)

Master prompt section 53.3 requires a controlled experiment behind a
`BENCHMARKED` candidate. What existed was `benchmark_plan` — a schema string —
and `STOP_REPORT_PRECONDITIONS`' `benchmark_plan_complete` — a boolean an agent
sets. Both describe what WOULD be measured. A repo-wide search for a
benchmark-execution function found none, so `EXPERIMENTING -> BENCHMARKED` was
an edge crossed by writing `reason="before/after measured"` into
`transition()`: no before, no after, no artifact, and section 63's
post-experiment PROMOTE/REVISE/HOLD/REJECT decision resting on a sentence.

`capability_evolution.run_controlled_experiment()` is the execution. It reuses
the existing machinery end to end rather than standing up a benchmark harness:

- **The stage runner is `engine.DVHarness.run_stage()`**, driven twice over the
  SAME stages against two copies of an isolated fixture project — `baseline`
  untouched, `treatment` carrying the candidate's bounded change. There is no
  second stage runner and no second gate evaluator.
- **The measurement is `control_plane.describe_stage()`**, already the one
  shared read path `dv-harness explain` and the dashboard both use for a
  stage's gate outcome, so an experiment can never disagree with what an
  operator reading the same project would see. `compare_experiment_arms()`
  orders on gate satisfaction first and stage completion second, and reserves
  INCONCLUSIVE for "neither arm had a gate to measure" so that case can never
  read as a real UNCHANGED.
- **The change is data, not narration.** `mutation` is either a list of
  `{"path", "content"}` writes (the auditable form, carried into the experiment
  record) or a callable returning the paths it wrote. Every path is resolved
  and checked to be inside the treatment copy before and after; a mutation that
  changes nothing is refused, because comparing a copy against an identical
  copy would report UNCHANGED and look like a real negative result.

**Four isolation properties, each enforced in code and each tested:**
1. **The isolated arm workspaces live under
   `<root>/.dv-harness/experiments/<candidate_id>/<run_id>/`.** Every harness is
   constructed rooted inside an arm of that workspace, and that is re-checked
   against the harness object actually returned — an injected `harness_factory`
   returning one rooted at the live project is refused before any stage runs.
   **Correction (three-loop gap-close review, 2026-09-05):** the arms are not
   the ONLY things written — `transition()`/`persist_candidate()` also write
   2 real Working Memory records plus an update to the Blackboard candidate
   topic, both outside the experiments directory, since those are the
   governance audit trail every other candidate uses, not part of the
   sandboxed experiment. What stays true: no path outside
   `.dv-harness/{experiments,memory,blackboard}` is touched, and nothing
   reaches the live project's own tracked source files.
2. **The source fixture is content-fingerprinted before and after.** A changed
   digest means the run was not isolated and its measurement is discarded, so
   "the experiment never wrote to the project it was copied from" is a checked
   fact rather than a design intention.
3. **An execution-layer stage is refused by default**, keyed on the same
   `vcs-build`/`devops-pipeline` node-skill discriminator
   `engine._execution_preflight_gate()` already uses. A capability experiment
   must never be the thing that quietly submits a farm build or a regression
   batch; `allow_execution_stages=True` is the explicit opt-in.
4. **A fixture that contains the live project root is refused**, so pointing the
   experiment at a parent directory cannot copy the live project into its own
   workspace.

**The evidence cannot be forged, and that is what actually closes the gap.**
`transition()` now refuses `-> BENCHMARKED` unless
`assert_benchmark_measured()` clears, and every check there re-reads disk: the
`benchmark_result` must carry the `produced_by` const, name a record under THIS
project's own experiments directory, that record must still exist, still hash to
the digest the candidate carries, and name this candidate and this run.
`build_candidate()` additionally refuses a caller-supplied `benchmark_result` —
a candidate is born four governance states before any experiment may run, so one
arriving there measured nothing. `benchmark_plan` is unchanged and still
required: it is the plan, and it is now only the plan.

**Nothing about the human-approval boundary moved.** Section 61's LEVEL B ends
at BENCHMARKED and `run_controlled_experiment()` asserts its own terminal state
before returning — a real, IMPROVED measurement is exactly the circumstance
under which someone would be tempted to carry the candidate one more step.
`PROMOTION_CANDIDATE` stays a human's move, `assert_human_approval()`'s real
`ControlPlane` check is untouched, and `assert_no_production_write_authorized()`
still refuses a BENCHMARKED candidate. The record states
`acceptance_criteria_machine_evaluated: false` explicitly rather than leaving it
to be assumed: the criteria are free text, this code does not judge them, and
deciding whether the measurement MEETS them stays with the human at the
approval gate.

**No verification verdict token reaches the candidate or the record.** The arms
really do produce gate verdicts; what is stored is the numeric gate counts plus
a HASH of the verdict string, so a before/after CHANGE is detectable while this
module keeps its "nothing here persists a member of `models.Status`" guarantee
(`BENCHMARK_OUTCOMES` — IMPROVED/UNCHANGED/DEGRADED/INCONCLUSIVE — is checked
for collision by `assert_no_verification_verdict_vocabulary()` alongside the
other three vocabularies). The unhashed verdicts stay in each arm workspace's
own harness state, which the record points at by path.

Proven end to end — two copies of a synthetic fixture, the REAL `run_stage()` in
each, the REAL `command_migration_integrity_gate.py` subprocess judging both
arms, a measured 0/1 -> 1/1 gate movement, and a candidate reaching BENCHMARKED
carrying numbers nobody typed — by
`dv_harness_tests/test_capability_evolution_controlled_experiment.py` (24 tests),
which also holds every boundary above and proves an edited, deleted, foreign or
hand-written experiment record is refused. The fixture is
`dv_harness_tests/controlled_experiment_fixture.py`; the only stub anywhere is
the agent adapter, because the real one dispatches a `claude -p` subprocess.

**Disclosed residual**: there is no CLI verb for this yet, and none of it is
engine-fired. `run_controlled_experiment()` is called by the `research-architect`
path (see `.claude/agents/research-architect.md`'s "Running the controlled
experiment" section) and by its tests — a REACHED capability, not a WIRED one.
The mutation is also still authored by whoever runs the experiment: nothing
derives a candidate's bounded change from its own `proposed_action` text, so
`experiment_plan` remains a plan a human or an agent enacts, in the same sense
`benchmark_plan` used to be one for the benchmark. What is closed is that the
BENCHMARKED state can no longer be reached without a real, isolated, re-readable
before/after run.



<!-- S056: moved verbatim from CLAUDE.md original lines 2616-2728 (M4.6 CLAUDE Context Normalization) -->
## LoopContract + the Canonical Loop State Machine (2026-09-05)

LOOP_ENGINEERING sections 85/86 require every important loop to carry a
`LoopContract` (budgets, convergence, plateau, oscillation, termination,
escalation, human gate, rollback, resume, audit) and to name its state in the
canonical vocabulary `CREATED -> READY -> RUNNING -> VERIFYING -> CONVERGING /
PLATEAU / OSCILLATING / RETRY_WAIT / BLOCKED / HUMAN_GATE -> SUCCESS / FAILED /
BUDGET_EXHAUSTED / STOPPED / CANCELLED`, plus `RESUMING`/`STALE`. A repo-wide
grep on 2026-09-05 returned ZERO hits for `LoopContract`, `loop_contract`,
`LoopState`, `BUDGET_EXHAUSTED` and `PLATEAU`. Three real loops were running the
whole time -- `engine.DVHarness.loop()`/`run_stage()` (Verification Closure),
`memory_router.route_and_store()`/`promote_to_organizational()` (Project
Learning) and `capability_evolution.py`'s 11 promotion states (Capability
Evolution) -- and not one could state its own budgets or name its own state.

`dv_harness/loop_contract.py` is that schema and that state machine.

**A SECOND enum, with ONE bridge -- not an extended `Status`.**
`models.Status` (models.py:74) is a stage-gate VERDICT vocabulary: it is
persisted in every `state.json`, it is what `policy.graph_next()` routes on, and
`gates.py`/`engine.py`/`dashboard.py`/`commands.py` all branch on its exact
members. Nine of section 86's states (CREATED, VERIFYING, PLATEAU, OSCILLATING,
FAILED, BUDGET_EXHAUSTED, CANCELLED, RESUMING, STALE) are not verdicts at all and
would be values every existing `if status in (...)` chain silently falls through
-- the same shape as `engine.loop()`'s own 2026-08-28 PARTIAL routing bug. So
`LoopState` is separate, and `STATUS_TO_LOOP_STATE` is the one real bridge, held
TOTAL in both directions by `assert_status_mapping_total()` (and
`assert_capability_state_mapping_total()` for the 11 promotion states) -- adding
a `Status` member without deciding its loop meaning fails a test rather than
falling through. Two mappings carry their reasoning: a stage `PASS` is
CONVERGING, not SUCCESS (SUCCESS is the LOOP's own machine-checkable done,
`overall_status == CLOSED`, or a run would claim a closed project once per
stage), and `ACCEPTED_RISK` is STOPPED, not SUCCESS (a human accepted residual
risk; the machine-checkable done was not met).

**Contracts are DERIVED from the drivers, never hand-maintained**, the same
policy `protocol_capability.py`'s registry follows. `max_stage_retries` is read
off the loaded config, `PROMOTION_STATES`/`TERMINAL_STATES`/
`HUMAN_APPROVAL_STAGE` and `ORGANIZATIONAL_MIN_CONFIRMATIONS` are imported from
their own modules, and `assert_driver_resolvable()` imports each contract's
`driver_module` and resolves its `driver_entry_point` -- so a contract cannot
outlive or misname the loop it documents. There is deliberately no `sync`/`set`
verb: a second, editable copy of a contract on disk would be the parallel
mechanism this project forbids.

**Absent budgets are stated, never implied.** Section 85 lists eight budgets;
this harness really enforces two (`max_failed_attempts` =
`policy.max_stage_retries`, and capability evolution's `max_change_scope` =
`run_controlled_experiment()`'s mutation containment check). Every other field is
`None` AND carries a real reason in `budget_sources` -- `validate_contract()`
refuses a contract with a budget key missing from it, because a `None` with no
reason reads to a human as a bound that exists. `loop()` really is an unbounded
`while True` over the graph with no wall-clock deadline, and the contract says so.

**BUDGET_EXHAUSTED is produced on the real engine path, not merely defined.**
`engine.DVHarness._record_loop_state_observation()` writes one
`LOOP_STATE_OBSERVED` event to `.dv-harness/events.jsonl` at the two places this
engine actually spends the retry budget -- `loop()`'s retry-exhaustion branch and
`_advance_with_fanout()`'s branch-failure branch, both one line after
`_record_debug_loop_round()`. Those recorded the ROUTING decision but never the
fact that a BUDGET was what ran out. Every field of the observation is read off
disk (`state.json` status/attempts, `config.json` `policy.max_stage_retries`,
`control.json` paused/takeover, the Blackboard `debug_loop_history` topic) --
never agent prose, per section 86's own rule. Best-effort, mirroring every
sibling `_record_*`: a failure records `LOOP_STATE_OBSERVE_FAILED` and never
turns an already-computed routing decision into a crash.

**Oscillation is computed from evidence the engine already persists.**
`detect_oscillation_from_debug_loop_history()` counts repeated
`(failing_stage, target_fail_edge)` pairs in the Blackboard `debug_loop_history`
topic `engine._record_debug_loop_round()` has been writing since 2026-09-01 --
exact-tuple matching on graph node ids the engine itself wrote, at the same
"2 INDEPENDENT observations" threshold `REPEAT_FAILURE_MIN_OCCURRENCES` and
`ORGANIZATIONAL_MIN_CONFIRMATIONS` already use.

**Plateau is honestly NOT evaluated.** Every observation carries
`plateau: PLATEAU_NOT_EVALUATED` plus the reason: plateau needs a
progress-metric series over iterations, whose real producers are
`trend_analysis.py` / `coverage_analysis.py`, and reporting "no plateau" without
one would be an unearned claim. A detector that never ran and a detector that
found nothing are different facts.

**No human-approval gate moved.** `HUMAN_GATE` is an OBSERVATION that a human
decision is owed and authorizes nothing: `ControlPlane.approve()`,
`policy.can_signoff()`, `assert_human_approval()`,
`assert_no_production_write_authorized()` and the PR-only main/master governance
are untouched and uncalled from this module.

Front door: `dv-harness loop-contract states|list|show <loop_id> [--format yaml]|observe`
(and the identical `python -m dv_harness.loop_contract`, one shared
`execute_verb()`). Proven -- including a REAL `DVHarness.loop()` over the REAL
shipped `main_graph.json` with the REAL `command_migration_integrity_gate.py`
subprocess reaching a real BUDGET_EXHAUSTED, its positive control (the same
fixture with the manifest present, observing CONVERGING), a real `ControlPlane`
pause/takeover, and a real `memory_router.route_and_store()` result -- by
`dv_harness_tests/test_loop_contract.py` (50 tests). The fixture is
`dv_harness_tests/controlled_experiment_fixture.py`, reused rather than
duplicated; COMMAND_PATTERN is an `implementation-route` node with no FAIL edge,
so a retry-exhausted loop stops deterministically and nothing here can reach a
build, a regression or an LSF submission.

**Disclosed residual**: this is the CONTRACT and the VOCABULARY, not the
convergence engine. Sections 88-90's PLATEAU/no-progress CLASSIFICATION was
closed the same day by `loop_convergence.py` (next section); their
`STOP BLIND RETRY -> reassess -> materially different strategy` RESPONSE is
still not built -- the engine routes a retry-exhausted stage onto its graph FAIL
edge exactly as before. Section 91's `LOOP_*` event taxonomy is also only partly
emitted (`LOOP_STATE_OBSERVED` / `LOOP_STATE_OBSERVE_FAILED`; the other nineteen
names have no producer). The Project Learning Loop is observed PER RECORD at a
`route_and_store()` result, so `observe_all()` honestly reports it
`NOT_OBSERVABLE` rather than inventing a project-wide aggregate nothing computes.



<!-- S057: moved verbatim from CLAUDE.md original lines 2729-2836 (M4.6 CLAUDE Context Normalization) -->
## Convergence, Plateau and Oscillation Detection (2026-09-05)

LOOP_ENGINEERING sections 88-90 require three classifiers the harness did not
have: a coverage-convergence verdict (`CONVERGING`/`SLOW_CONVERGENCE`/
`NO_PROGRESS`/`PLATEAU`/`REGRESSION`/`OSCILLATING`/`UNKNOWN`), plateau detection
with an unreachable-bin / stimulus-gap investigation, and fingerprint-based
oscillation / no-progress detection (repeat-failure and repeat-fix-revert). The
section above is where the gap was DECLARED, in its own disclosed residual:
`observe_*` reported `PLATEAU_NOT_EVALUATED`, and `LoopPlateau.detection_window`
/ `minimum_gain` and `LoopConvergence.minimum_progress` / `window` were all
`None` on the verification-closure contract because nothing computed them.

`dv_harness/loop_convergence.py` is the DETECTOR half; `loop_contract.py` stays
the vocabulary half. Front door: `dv-harness loop-contract convergence` (exit 2
when no usable series exists), and `... observe` now carries the report.

**Every number is read from a producer this project already has.** Not one is
re-derived: the series is `trend_analysis.daily_rollup()`'s own bins-weighted
`coverage_percent` curve; the repeat-FAILURE fingerprint is
`loop_contract.detect_oscillation_from_debug_loop_history()`, CALLED not copied,
so there is exactly one definition of it; the "flat" band is
`coverage_analysis.FLAT_TREND_TOLERANCE_PERCENT` (an inline `0.5` until this
change), so this classifier and `compute_coverage_trend()` cannot disagree about
the identical series; and every threshold is derived from a number this codebase
already defends -- `min_gain` is 2x the noise floor (so a series sitting on the
tolerance band's edge reports SLOW_CONVERGENCE rather than being promoted), and
`plateau_window` is 3 samples = 2 consecutive no-movement INTERVALS, the same
"2 INDEPENDENT observations" bar `REPEAT_FAILURE_MIN_OCCURRENCES` and
`ORGANIZATIONAL_MIN_CONFIRMATIONS` use. `capability_evolution.
repeated_unresolved_failure_patterns()` is adjacent and deliberately NOT called:
its thresholds are purpose-built for filing a capability candidate, and a loop
verdict must not depend on whether one was filed.

**The one genuinely new detector is `trend_analysis.detect_verdict_oscillation()`**
-- section 90's repeat-fix-revert, added beside `detect_pattern_regressions()`
because that is the module that reads `regression_verdict_history`. It counts
completed FAIL -> PASS -> FAIL cycles after COLLAPSING consecutive duplicate
verdicts (five green nightlies are one PASS state, not five), and the SHAs
decide what the flapping MEANS, the same way `detect_pattern_regressions()`
already reasons about `SAME_GIT_SHA_PASSED_AND_FAILED`: `FIX_REVERT` (>= 2
distinct SHAs) is real loop oscillation; `FLAKY_SAME_SHA` (one commit that both
passed and failed) is an intermittent test and is reported but never counted as
loop oscillation, because answering a flake with "change strategy" points the
loop at the wrong problem; `UNDETERMINED_NO_SHA` cannot tell the two apart and
says so while still reporting the instability.

**Plateau detection reuses the existing per-bin classifier and escalates
nothing.** `investigate_plateau()` runs `coverage_analysis.
classify_coverage_hole()` -- which already measures distinct seed attempts
against real `jobs` rows and refuses an "unreachable" claim on an under-sampled
bin -- and adds only the LOOP-level next action, applying that same precedence
one level up: any under-sampled bin makes the plateau PREMATURE and routes to
ADD_SEEDS; otherwise a stimulus gap routes to generate/adjust; otherwise an
adequately-sampled unreachable bin requires a human. It NAMES
`escalate_unreachable_holes()` as the real escalator and does not take that
path -- reading a loop's state must never be a mutating act, and nothing here
writes a question, an approval or a file.

**PLATEAU and OSCILLATING now reach a real `LoopObservation`.**
`derive_loop_state()` gained `plateau` / `progress_oscillating`, which apply
only over CONVERGING and only while the loop is not done. They apply exactly
where the existing `oscillating` argument does not, and the difference is which
evidence each reads: `oscillating` is the `debug_loop_history` repeat-FAILURE
record, so it says nothing about a stage that has since passed and stays
confined to the retry family; these two read CURRENT cross-run evidence, and a
loop whose stages keep PASSING while its own progress metric has stopped moving
is exactly what PLATEAU is for. `progress_oscillating` wins over `plateau` (the
more specific fact, pointing at a different remedy), and Human Override still
outranks both. The verification-closure contract's convergence/plateau blocks
are now read from this module's constants rather than being `None`.

**`PLATEAU_NOT_EVALUATED` survives, deliberately.** A project with no evidence
database, or one whose days carry no coverage sample, still reports it -- with
the real distinct reason (`NO_EVIDENCE_DATABASE` vs `NO_COVERAGE_SAMPLES`,
different operator problems with different fixes). A detector that never ran and
a detector that ran and found nothing are different facts; the arrival of a real
detector must not turn the first into a cheerful "no plateau".

**No human-approval gate moved.** `ControlPlane.approve()`,
`policy.can_signoff()`, `assert_human_approval()`,
`assert_no_production_write_authorized()`, `HumanApprovalRequiredError`,
`ProductionWriteNotAuthorizedError` and the PR-only main/master governance are
untouched and uncalled from this module, and the evidence database is opened
READ-ONLY exactly as `trend_report()` opens it.

Proven by `dv_harness_tests/test_loop_convergence.py` (53 tests) against REAL
evidence rows written through the REAL production write paths
(`regression_reporter._write_reconciliation_evidence_if_configured()` and
`dashboard.append_coverage_history_sample()`, the exact functions `lsf_client`
and `engine.py` call) -- including all seven verdicts driven out of real series,
and the negative controls that give the detectors their power: a spike-and-crash
whose net is flat is NOT a plateau, a same-SHA flip-flop is NOT loop
oscillation, sub-threshold jitter has no direction to reverse, and a long green
streak does not inflate the cycle count. Nothing in it runs a build, a
regression or an LSF submission.

**Disclosed residual**: this is the CLASSIFIER, not the RESPONSE.
Sections 88-90's `STOP BLIND RETRY -> reassess -> materially different strategy`
is still not built -- `engine.loop()` routes a retry-exhausted stage onto its
graph FAIL edge exactly as before, and nothing terminates or re-plans a run on a
PLATEAU verdict. It is also not engine-fired: `classify_loop_convergence()` is
reached from the CLI verb and from `observe_all()`, and no `run_stage()` /
`advance()` call site invokes it, so this is a REACHED capability, not a WIRED
one. The series is the coverage curve only; `stage_completion_percent` and
`findings_open` are named in the contract's `convergence.metrics` but have no
cross-run producer to build a series from.



<!-- S059: moved verbatim from CLAUDE.md original lines 2948-3032 (M4.6 CLAUDE Context Normalization) -->
## Golden Flow Readiness Matrix: `dv-harness golden-flow-readiness` (2026-09-05)

Section 47 mandates that a complete L5 audit report a twenty-row table --
`Golden Flow Stage | Status | Evidence | Gap | Next-Best-Action` -- and rules
that "the Golden Flow is READY only when required stages are connected
end-to-end with evidence". Every per-domain fact that table aggregates was
already real and queryable; nothing rendered them into the document's row
shape, so the matrix existed only as prose an auditing session assembled by
hand and two audits of the same project could disagree about the same facts.
`dv_harness/golden_flow_readiness.py` is that renderer and nothing else.

**It derives nothing an existing reader already supplies.** Each row records
the reader it consulted in its own `fact_source`, and
`assert_fact_sources_resolvable()` resolves every one through the import
system -- a row claiming to read `dashboard._coverage_credit` after that
function was renamed away is a row whose provenance is fiction. The readers
are the ones already in production: `state.json` via
`dashboard._read_json_file()`, `gates.effective_stage_gates()`,
`dashboard._read_coverage_state()` / `_lsf_summary()` / `_failure_attribution()`
/ `_coverage_credit()` / `_qualified_conclusion()` / `_protocol_registry()` /
`_read_memory_center_state()`, `coverage_analysis.identify_holes()` /
`classify_coverage_hole()`, `signoff_export.read_signoff_stage_status()`,
`env.manifest.json`'s `testplan_correspondence`, `loop_contract.observe_all()`,
`memory_doctor.check_obsidian()` and `ClaudeCLIAdapter._resolve_command()`.

**The vocabulary is borrowed, not minted.** Status is
`subsystem_discovery`'s READY/PARTIAL/BLOCKED/UNKNOWN -- the same four words
`system_readiness.py` already reused one level up -- and
`STATUS_TO_READINESS`'s totality over `models.Status` is asserted at import,
so a new Status member fails loudly instead of silently rendering UNKNOWN.
`ACCEPTED_RISK` floors to PARTIAL: a human accepting residual risk is a real
decision, not evidence the stage is connected end-to-end. The
Next-Best-Action column is produced by the REAL
`inference.next_best_action()` through its `gap_action_catalog` parameter --
the same domain-neutral engine `capability_evolution.py` already drives with
its own catalog, and the one section 10 forbids re-implementing.

**Every row is always printed, including its absences.** Twenty rows are
mandatory, so a project with nothing on disk reports twenty UNKNOWNs with a
real reason each -- "this row is unknown" and "this row was omitted" must not
look alike once the table is printed. `_assert_rows_match_section_47()`
compares the declarations against a transcription of the specification's own
list rather than against themselves.

**Reading is not a mutating act.** No stage runs, no gate script is invoked,
no state/control/approval file is written. `state.json` is read through
`_read_json_file()` rather than `StateStore.load()` (which would MINT one),
`config.load_config()` is skipped for a project with no `config.json` (it
would materialize a default), and `loop_contract.observe_all()` -- which does
go through `StateStore` -- is called only when a real `state.json` already
exists. Disclosed precisely: the CLI WRAPPER still constructs a `DVHarness`
and appends the usual `CLI_ACCESS` audit event before dispatch, exactly as
`status`/`explain` do; `python -m dv_harness.golden_flow_readiness` carries
the untouched-tree guarantee.

**No human-approval gate moved.** The verdict authorizes nothing and the
module has no write path to any approval record: `ControlPlane.approve()`,
`policy.can_signoff()`, `assert_human_approval()` and the PR-only
main/master governance are untouched and uncalled from it. Exit 2 unless
every row is READY -- a CI signal, not an approval signal in either
direction.

Front door: `dv-harness golden-flow-readiness [--json]`, and the identical
`python -m dv_harness.golden_flow_readiness`, one shared `execute()`. Proven
against REAL artifacts written by their REAL writers -- a real `StateStore`
state.json, real `.dv-harness/lsf/jobs/*.json`, a real coverage
`summary.json`, a real `MemoryStore` record, a real capability registry --
and with the CLI driven as a real subprocess, by
`dv_harness_tests/test_golden_flow_readiness.py` (39 tests). Its negative
controls are what give it detection power: an LSF job at DONE with no DV
analysis does NOT read as passing, a stage PASS with no spec on disk does NOT
close Spec In, a PROJECT_MODEL PASS with no IR evidence block does NOT close
Verification IR, a malformed coverage summary is BLOCKED rather than "no
coverage yet", and dropping a row from `ROWS` fails the section-47 check.

**Disclosed residual**: section 55's SELF-LEARNING READINESS MATRIX (22 rows
over the research/capability-evolution and five-tier-memory surfaces) is NOT
built by this module -- it is a different row set over different sources, and
producing a half-sourced version of it would be the fabrication this module
exists to prevent. It is also not engine-fired and not exposed on the
dashboard: no `run_stage()`/`advance()` call site invokes it and no graph node
declares it, so this is a REACHED capability (a real CLI caller exists), not a
WIRED one.



<!-- S060: moved verbatim from CLAUDE.md original lines 3033-3182 (M4.6 CLAUDE Context Normalization) -->
## Unified Loop Budget + Failure Taxonomy + Circuit Breaker (2026-09-05)

LOOP_ENGINEERING sections 91/92/93 require a unified budget engine over eleven
dimensions with exhaustion that is explicit and cannot silently reset, a
ten-class failure taxonomy feeding a retry-vs-stop decision, and a circuit
breaker. A repo-wide grep on 2026-09-05 returned ZERO hits for
`circuit_breaker`/`CircuitBreaker` and exactly ONE for `TRANSIENT` -- an
unrelated sentence in `connectivity.py`'s Gate-3 docstring. Real budgets existed
and were being spent (`policy.max_stage_retries` in `engine.loop()`,
`policy.inner_react_max_iterations`/`inner_react_max_adapter_calls` in
`react_loop.InnerReactLoop`, `context_budget.MAX_PACK_BYTES` for the resident
pack) but each lived alone: nothing could answer "what has this RUN spent, on
which dimension, against which limit, and has any of it run out". And nothing
classified WHY a stage failed, so `loop()`'s retry decision was
`ss["attempts"] <= max_retry` and nothing else -- a deterministic compile error
and a dropped API connection were retried identically.

`dv_harness/loop_budget.py` is all three, in one module because they are one
mechanism: the breaker trips on the budget engine's exhaustion and decides
retry-vs-stop from the taxonomy, which section 92's resource-pressure signal
also feeds.

**Every input names its real producer; nothing is re-derived.** The LIMITS are
read from the budgets this harness already has, never retyped. The exhaustion
vocabulary is `loop_contract.LoopState.BUDGET_EXHAUSTED`, imported. The triage
categories map from `sim_log_analysis.TRIAGE_CATEGORIES` -- whose own docstring
invites exactly this -- and the DUT-vs-testbench call comes from
`tools/senior_dv/failure_attribution.py`'s boundary-trace rule, recomputed the
same way `dashboard._failure_attribution()` recomputes it rather than trusting
an agent-written `classification` field. The resource evidence is
`preflight.check_license()`/`check_queue_health()`'s own `CheckOutcome`s,
reached through `degradation.probe_resources()`. The failure SIGNATURE is
`sim_log_analysis.normalize_failure_signature()` (the existing private
`_normalize_signature`, made public for this): two different answers to "is
this the same failure" is exactly how a breaker either never trips or trips on
nothing.

**No dimension is bounded by default, and every one says why.** That is the
honest state of this harness: it enforces no run-scoped loop budget today.
`policy.max_stage_retries` is deliberately NOT reported as a run-wide
`max_retries` cap -- it is a PER-GRAPH-NODE budget that resets when
`current_stage` moves on, and treating it as run-wide would report every second
retry-exhausted stage as an exhausted RUN (confirmed the hard way: the first
build did exactly that and broke
`test_loop_contract.py::test_a_second_identical_failure_is_a_real_oscillation_fingerprint`).
Its per-node spends ARE accumulated into the ledger so the run-wide total is
visible; a real cap is `loop_budget.limits.max_retries`. Every `None` limit
carries a real reason, the same honesty contract
`loop_contract.validate_contract()` enforces on a `LoopContract`.

**Exhaustion cannot silently reset.** `reset()` and `reset_breaker()` both
REQUIRE a real `reason` AND a real `by`, refuse without them, append an
append-only record of the spend that was cleared, and leave the
`exhaustion_log` intact -- there is no code path in the module that zeroes a
spend without producing that record. Section 91's one hard rule, enforced
rather than described.

**RECORD-FIRST on the real engine path; the two behaviour-changing halves are
opt-in.** `engine.loop()`'s retry-exhaustion branch now classifies the failure
(`_classify_stage_failure()`, reading `state.json`'s own `blocking_reason` and
the FAILURE_RECOVERY `failure_attribution` boundary trace -- never agent prose)
and spends the unified ledger (`_spend_retry_exhaustion_budget()`), recording
`LOOP_BUDGET_SPENT` in `.dv-harness/events.jsonl` and
`failure_type`/`failure_signature`/`failure_signature_repeats` on the stage
state, on every default run. What is OPT-IN, for the same disclosed-default
reason `require_tier` and `probe_resources` are:
`loop_budget.enforce_retry_policy` (make a non-retryable classification
actually stop a retry -- turning it on shortens a stage's real retry budget,
which is a project's decision, not this module's) and
`loop_budget.repeated_identical_failure_threshold` (section 93's "repeating the
identical UVM_FATAL is not a useful retry"). UNKNOWN is retryable ON PURPOSE:
refusing to retry a failure nobody classified would shrink every existing
project's budget on the strength of this module's ignorance.

**The breaker BLOCKS by default -- it just has nothing to trip on until a
project declares a budget.** `_circuit_breaker_gate()` runs at the top of every
`loop()` cycle, AFTER both Human Override checks (a takeover/pause always
outranks it -- an operator must never have to clear a breaker to take control
back) and BEFORE the SIGNOFF gate and `run_stage()`. An OPEN breaker marks the
stage BLOCKED with the real trip evidence and returns: STOP NEW ACTIONS, with
the recovery condition being a recorded `dv-harness loop-budget breaker-reset
--reason ... --by ...`. `loop_budget.trip_on_oscillation` is a real, wired
trigger -- `loop_contract.detect_oscillation_from_debug_loop_history()` CALLED
over the very `debug_loop_history` entries `_record_debug_loop_round()` wrote
one line earlier, so there is one definition of an oscillation fingerprint in
this codebase -- but it stays OFF by default with an honest reason: `loop()`
currently routes an oscillating stage onto its graph FAIL edge, and sections
88-90's RESPONSE half is explicitly not built (see that section's own disclosed
residual), so tripping there by default would change routing this harness has
not decided to change.

**Section 92's missing half is PRIORITIZATION, and it lives where the real
measurement already happens.** The check-before-submit half was already real in
`preflight.py`. `engine._execution_preflight_gate()`'s PASS branch now re-reads
the SAME `CheckOutcome`s it just produced (never a second lmstat round trip) for
the band BETWEEN "plenty" and "fully checked out" -- the range `degradation.py`
deliberately says nothing about, since it only trips at starvation. `preflight`
gained a public `parse_license_availability()` and now carries the raw lmstat
output on the PASS path too, so headroom is re-derived through the check's own
parse instead of scraping its formatted `detail`. `PROCEED` /
`PROCEED_CRITICAL` / `DEFER` is decided by three rules with reasons a human can
check: no measured pressure never defers (section 92: do not invent
availability -- and equally, do not invent scarcity, so UNKNOWN never defers);
work whose graph node declares no execution-layer skill never defers (deferring
it would delay the project and free nothing); and critical signoff-family work
proceeds under pressure by policy. The measurement is ALWAYS recorded in the
`EXECUTION_PREFLIGHT_PASS` event; acting on it is
`loop_budget.defer_low_value_under_pressure` (off by default), it can only ever
DEFER, and it can never let a stage preflight BLOCKED proceed.

**No human-approval gate moved.** `ControlPlane.approve()`,
`policy.can_signoff()`, `assert_human_approval()`,
`assert_no_production_write_authorized()`, `HumanApprovalRequiredError`,
`ProductionWriteNotAuthorizedError` and the PR-only main/master governance are
untouched and uncalled from this module -- asserted against its own tokenized
source by a test, so a future edit that reaches for one fails. Everything this
mechanism can do is STOP work; nothing here authorizes any.

Front door: `dv-harness loop-budget dimensions|status|classify|reset|breaker-reset`
(and the identical `python -m dv_harness.loop_budget`, one shared
`execute_verb()`). Proven by `dv_harness_tests/test_loop_budget.py` against a
REAL `DVHarness.loop()` over the REAL shipped `main_graph.json` with the REAL
`command_migration_integrity_gate.py` subprocess -- a real declared budget
exhausting, a real breaker trip, a real second `loop()` refusing to spend an
attempt, a real recovery releasing it, and a real takeover still outranking it
-- plus REAL `preflight.check_license()` outcomes over this project's own REAL
captured `lmstat` transcript. The fixture is
`dv_harness_tests/controlled_experiment_fixture.py`, reused rather than
duplicated; nothing in it runs a build, a regression or an LSF submission.
Every behaviour-changing assertion carries its negative control: the
retry-refusal test asserts three attempts with the flag off and one with it on
over the identical fixture, the repeat counter is proven to RESET on a
genuinely different failure, and the deferral test asserts PROCEED at the real
captured 99/0 license reading and DEFER only once the reading is genuinely
scarce.

**Disclosed residual**: this is the BUDGET, the TAXONOMY and the BREAKER, not
section 94's next-best-action ranking or section 95's utility telemetry -- the
ledger measures the cost dimensions those would need, and nothing ranks or
reports them. Section 91's `max_compute` / `max_license_usage` /
`max_token_cost` / `max_lsf_jobs` / `max_parallel_jobs` have no producer in this
harness at all, so they are declared and spendable but nothing spends them. The
only engine call sites are `loop()`'s retry-exhaustion branch and
`_execution_preflight_gate()`'s PASS branch, so a run that never exhausts a
stage's retries never touches the ledger, and `FailureType.VIP` is reachable
only from the declared Synopsys `svt_` component prefix -- a project using
another VIP vendor must declare its own `loop_budget.vip_component_prefixes`,
because guessing one would be fabrication.



<!-- S064: moved verbatim from CLAUDE.md original lines 3539-3657 (M4.6 CLAUDE Context Normalization) -->
## Shadow / Digital-Twin Validation: One Good Run Is Not Proof (2026-09-05, VI-3)

VERIFICATION_INTELLIGENCE's completeness audit flagged Shadow / Digital-Twin
Validation NEVER_BUILT. A repo-wide grep on 2026-09-05 for
`shadow`/`digital_twin`/`digital twin` returned only unrelated hits (Python
variable shadowing, W1C shadow registers, a coverpoint's `cp_*` shadow member),
so the NAME was genuinely absent -- but half the MECHANISM was not. Section
133's canonical picture is one input evidence set, two arms (current L5
production behavior vs. the candidate), a comparison of the two results, and a
candidate whose output alters nothing until it is promoted. That is what
`capability_evolution.run_controlled_experiment()` already IS: two copies of an
isolated fixture, the untouched one standing for production, the mutated one
carrying the candidate's bounded change, both driven through the REAL
`DVHarness.run_stage()` and measured through the REAL
`control_plane.describe_stage()`. So section 133 was closed under another name,
and building a second "shadow runner" beside it would have been exactly the
parallel mechanism the Methodology Consolidation Rule forbids.

**What was genuinely missing is section 134's promotion flow around it** --
`Candidate -> Shadow Runs -> Benchmark -> Regression Safety -> Stability Window
-> Promotion Candidate -> Human Gate`, and its own closing lines "provide
rollback" and "a single successful shadow run is not sufficient proof". Before
this change ONE run reached BENCHMARKED and `BENCHMARKED ->
PROMOTION_CANDIDATE` carried no evidence requirement at all. Four additions,
all in `capability_evolution.py` beside the machinery they extend:

- **`run_shadow_replication()` -- shadow runs, PLURAL.** It re-measures an
  already-BENCHMARKED candidate over the same fixture, arms and stages, reusing
  `_prepare_shadow_run()` / `_execute_shadow_run()` (extracted from
  `run_controlled_experiment()`, so both paths share one set of isolation
  checks, one record shape and one stage runner). It makes **no governance
  transition**: `PROMOTION_STATES` is section 70's table and gains no edge,
  because a replication is more evidence for the state the candidate is already
  in, not a step toward the next one. That is asserted on the way out, the same
  way `run_controlled_experiment()` asserts its terminal state.
- **`regression_safety()` -- the per-stage view a net verdict cannot give.**
  `compare_experiment_arms()`'s `outcome` is a NET verdict over arm totals, so a
  treatment arm that satisfies two more gates on one stage and one fewer on
  another totals +1 and reads IMPROVED with the broken gate invisible. It is
  computed from each run's own `before`/`after` at read time rather than trusted
  from a stored field, so it holds for records written before it existed and
  cannot be forged by editing one. A stage the treatment stopped measuring
  entirely is unsafe too -- that is the one way a regression hides from a check
  that walks only the intersection.
- **`assert_stability_window()` -- a NEW PRECONDITION on `BENCHMARKED ->
  PROMOTION_CANDIDATE`**, wired in `transition()` beside the existing
  `-> HUMAN_APPROVED` and `-> BENCHMARKED` evidence checks, and only from
  BENCHMARKED (the `PROPOSED -> PROMOTION_CANDIDATE` edge belongs to a candidate
  whose own `experiment_required` is False, which ran no experiment and has no
  window to establish). It requires `STABILITY_WINDOW_MIN_RUNS = 2` countable
  runs -- two for the same reason `REPEAT_FAILURE_MIN_OCCURRENCES` and
  `memory_router.ORGANIZATIONAL_MIN_CONFIRMATIONS` are two -- measuring the same
  stage set, agreeing on an outcome that is IMPROVED or UNCHANGED, none
  regressed, and a non-empty `rollback_plan`. `stability_window_status()`
  reports every blocker at once rather than one per round, because the caller is
  deciding whether to run another replication or to stop and fix something.
- **`shadow_rollback_manifest()` -- "provide rollback" as data.**
  `rollback_plan` is prose authored before anything ran; the manifest is the
  other half, derived from the experiment's OWN untouched baseline arm: for
  every path the mutation wrote, what the control copy holds there, so the undo
  is `delete` or `restore_content` with a baseline digest to check against. It
  reads only -- producing it is the mechanism, applying it is a Level C act that
  stays behind the human-approval gate like every other production write.

**A run counts because the CANDIDATE pins it, never because a file appeared in a
directory.** This is the same anti-forgery pattern `assert_benchmark_measured()`
established, extended to every later run: `benchmark_result` pins the first and
the new `shadow_runs` schema field pins each replication, each by
`record_path` + `record_digest`, and the window counts pinned runs ONLY. Every
check re-reads disk -- the record must exist, still hash to what the candidate
carries, name this candidate and this run, sit under this project's own
experiments directory, and be its own directory's record. The pin's own copy of
the outcome is never trusted; the record on disk decides. And because a digest
proves a record was not EDITED rather than that anything ever RAN, both arm
workspaces must still be on disk carrying real harness state.
`build_candidate()` refuses a caller-supplied `shadow_runs`, mirroring its
`benchmark_result` guard.

**No human-approval gate moved, and the window buys no authority.** Adding a
precondition in front of an edge that had none can only tighten it:
PROMOTION_CANDIDATE was and remains a state a human puts a candidate into,
`assert_human_approval()`'s real `ControlPlane` check is untouched,
`assert_no_production_write_authorized()` still refuses a promoted candidate,
and the PR-only main/master governance is unchanged. Whether a measurement MEETS
the candidate's free-text acceptance criteria is still not judged in code --
`acceptance_criteria_machine_evaluated: false` is carried on the window evidence
too, exactly as the experiment record already carried it.

Proven by `dv_harness_tests/test_capability_evolution_shadow_validation.py`
(24 tests) against the same synthetic fixture the controlled experiment uses --
real `run_stage()` in both arms of every run, the real
`command_migration_integrity_gate.py` subprocess judging both, and real
replications measured on disk rather than records written by hand. The negative
controls are what give it detection power: a genuinely-improving real run is NOT
reported as a regression, an unpinned record dropped into the experiments
directory counts for nothing, a `+2/-1` trade that totals IMPROVED is caught by
the per-stage view while its stored verdict still says IMPROVED, a pin whose
stage list was edited does NOT change the verdict (the record decides), and the
`experiment_required: false` edge still walks. Three existing tests that
promoted on one run now measure a second real one instead of the requirement
being relaxed. Nothing in it runs a build, a regression or an LSF submission.

**Disclosed residual, and it is the honest boundary of what this repo can
stand up.** (1) Section 133's compare list names accuracy, false
positives/negatives, coverage gain, runtime, resource cost and human-review
burden. What is compared here is what this harness can measure without ground
truth it does not have: gate satisfaction, stage completion, a per-stage
regression check and a gate-outcome digest. Scoring a candidate's false-positive
rate needs a labeled corpus of known-correct verdicts that does not exist in
this repo, and inventing one would be the fabrication this module exists to
prevent. (2) Section 134's `Limited Rollout` and `Revalidation` nodes are not
built: both are acts on production, and Level C stays human-governed. (3) The
rollback manifest is produced, never applied. (4) Like
`run_controlled_experiment()` before it, this is REACHED, not WIRED -- there is
no CLI verb and no engine call site, the caller is the `research-architect` path
and these tests, and the mutation is still authored by whoever runs the
experiment rather than derived from the candidate's own `proposed_action`.



<!-- S066: moved verbatim from CLAUDE.md original lines 3782-3931 (M4.6 CLAUDE Context Normalization) -->
## Global Cross-Job Resource Orchestration (2026-09-06, VI-5)

VERIFICATION_INTELLIGENCE's completeness audit flagged a Global Resource /
License Orchestrator NEVER_BUILT. Re-verified by direct search before building:
a repo-wide grep for `cross_job` / `arbitrat` / `global_resource` /
`resource_orchestr` / `multi_job` / `concurrent_jobs` over `dv_harness/` and
`tools/` returned only AMBA bus-arbitration text, the SoC shared-VIP ownership
family (`system_resource_inventory.py` / `system_resource_registry.py` /
`system_scheduling_plan.py` -- a different domain entirely: VIP/agent/BFM
composition, not license seats or farm slots) and gate names. Nothing ranked
two jobs against one measured pool. The gap is real, and so is the trap in it:
three real mechanisms sit right next to it and none of them is a cross-job
arbiter.

- `preflight.check_license()` / `check_queue_health()` are real probes (a real
  `lmutil lmstat -a -c <server>` parse, a real `bqueues <queue>` parse). They
  answer "may THIS submission proceed" and say nothing about who else is asking.
- `lsf_client.bsub_submit_with_preflight()` runs those checks in front of ONE
  `bsub` and blocks that one submission on a FAIL.
- **LOOP-3's `loop_budget.prioritize_stage()` is the overlapping half, and it
  is genuinely single-loop.** It takes one stage and one pressure reading and
  has no argument through which a second job could ever be visible to it. Under
  `PRESSURE_NONE` it returns PROCEED for every contender -- so ten jobs and two
  free seats is ten PROCEEDs. That is asserted as a test
  (`test_negative_control_loop_budget_alone_grants_all_five`), not described.

`dv_harness/resource_orchestrator.py` adds exactly the missing decision:
turning ONE measured capacity into a BOUNDED grant set over N contenders.

**Nothing is measured twice, and no probe is added.** Every resource fact
arrives as a real `preflight.CheckOutcome` -- supplied by the caller, or
obtained through `degradation.probe_resources()` when a transport is explicitly
injected. Pressure is `loop_budget.pressure_from_checks()`, CALLED, so this
module and the engine's own section-92 deferral can never disagree about
whether the farm is under pressure. The per-contender verdict is
`prioritize_stage()`, CALLED once per contender and carried through verbatim
with its reason: a DEFER is never overturned into a GRANT, and a PROCEED is
never turned into a DEFER. The one new fact is `slots_available`, and it comes
from public wrappers over `preflight`'s OWN parses -- `parse_license_availability()`
(already public, LOOP-3's precedent) plus the new `parse_queue_capacity()` over
the SAME `_parse_bqueues_output()` `check_queue_health()` uses to reach its
verdict. `check_queue_health()`'s PASS path now carries its raw bqueues text
for the same reason `check_license()`'s already did: "Open:Active" says the
queue ACCEPTS work, not how much room is left on it, and the arbitration
decision lives exactly in that band.

**Three decisions, and the middle one exists only at this level.** GRANTED /
QUEUED / DEFERRED, deliberately distinct tokens from `models.Status` and from
`loop_budget.PRIORITY_*`. QUEUED is the value no per-job check can produce,
because it is a statement about the OTHER contenders.

**The ranking rule is data, printed on every plan** (`RANKING_RULE`), so a
reader sees the rule that was applied rather than trusting a docstring:
(1) `prioritize_stage()`'s tier, PROCEED_CRITICAL before PROCEED -- and that
tier separates them only under measured pressure, because that is the only
circumstance section 92 escalates in, and inventing a permanent priority for
SIGNOFF would be a rule section 92 does not state; (2) fewest farm slots the
asking project ALREADY holds, from the real `bjobs` listing intersected with
that project's own registered job ids -- the anti-monopoly signal that exists
only here, since no per-job check can see how much of the farm the asker
already has; (3) oldest `requested_at` first (FIFO, starvation-free), a request
declaring no arrival time sorting last rather than being given a fabricated
one; (4) project_id then stage, purely so two runs over the same inputs produce
the same plan.

**Scarcity is never invented, in either direction.** An unmeasured capacity is
`slots_available: None` and every eligible contender is GRANTED with the reason
saying so -- deferring real work because nothing was measured would be section
92's "do not invent availability" rule broken from the other side. LSF's `-`
(no limit) is None and never 0; reading an unlimited queue as a full one would
defer every job on the farm. A FAILing license or queue check contributes NO
capacity number either: a starved pool is `PRESSURE_CRITICAL`, which every
contender already reads through `prioritize_stage()`, and restating it as a
capacity of 0 would double-count one fact. Live jobs are OBSERVED and never
subtracted, because lmstat's `in_use` and bqueues' `NJOBS` already count them.
"Nobody looked" and "this project holds nothing" stay distinct: with no live
listing every `held_slots` is None and the fairness term is inert rather than
silently reordering on a fact nobody measured.

**A grant authorizes nothing and reserves nothing.** It says only "of the
contenders asking, this one is next". Every existing gate still stands in front
of any real work -- `preflight.run_preflight()`, `bsub_submit_with_preflight()`'s
`PreflightBlockedError`, `policy.can_signoff()`, `ControlPlane.approve()`, the
PR-only main/master governance -- and a GRANTED contender whose own preflight is
BLOCKED stays blocked. This module submits nothing, kills nothing, holds no lock
and writes no state, control, approval or memory record; it constructs no
`MemoryStore`/`StateStore`, so a project with no `state.json` is reported as
having none rather than having one minted for it. Both boundaries are asserted
against the module's own CODE tokens (comments and docstrings stripped by the
same `tokenize` approach `test_loop_budget.py` established, since this module's
prose deliberately names the gates and submission verbs it stays away from).

**Cross-PROJECT contenders come from the registry this codebase already has.**
`contenders_from_registry()` reads `cross_project_mining.ProjectRegistry`,
including its `ProjectIdentityCollisionError` guard, so one memory store
registered twice cannot appear as two contenders and manufacture a contention
out of one project's audit trail. Each project's stage is read from its own
`state.json` with a plain `read_text()`; whether that stage consumes the scarce
resource is derived from the project's OWN graph node skills against
`engine.DVHarness.EXECUTION_PREFLIGHT_SKILLS`, never from the stage name. A
project whose state or graph cannot be read contributes a real skipped-reason
and no contender -- inventing one would put a project into an arbitration it
never asked to join.

Front door: `python -m dv_harness.resource_orchestrator
ranking-rule|contenders|capacity|plan [--requests <json>] [--queue <q>]`, one
shared `execute_verb()`. `plan` exits 2 when any contender is held back and
`capacity` exits 2 when nothing was measured -- a CI-visible "someone is waiting
on capacity", never an approval signal in either direction.

Proven by `dv_harness_tests/test_resource_orchestrator.py` (53 tests) against
this project's OWN real captured `lmutil lmstat` / `bqueues` transcripts,
imported from `test_preflight.py` rather than re-typed and mutated only in the
numbers that carry the meaning under test. The multi-job LSF state is a
clearly-labelled FIXTURE (`_bjobs_records()` builds records in
`discover_live_jobs()`'s exact real shape) because this project has no
multi-job farm to measure; nothing in the suite contacts a live license server,
scheduler or farm, and nothing runs a build, a regression or an LSF submission.
The negative controls are what give it detection power: `prioritize_stage()`
alone grants all five contenders where the orchestrator grants two, the grant
set shrinks with the measured capacity, an unmeasured capacity grants
everything, a small request cannot jump a blocked head-of-line one, a project
holding three farm slots loses to a newcomer that asked two hours later while
the SAME pair reverts to FIFO once the live listing is withheld, and all three
ranking claims were mutation-checked (removing the anti-monopoly term,
removing head-of-line blocking, and letting an unmeasured held-slot count read
as zero -- each fails exactly one test and nothing else).

**Disclosed residual.** (1) Like `cross_project_mining.py`,
`confidence_calibration.py` and `verification_strategy.py` before it, this is
REACHED, not WIRED: there is no `dv-harness` CLI verb (`cli.py` was being
modified by concurrent work in the same session and adding a verb there would
have collided), no `run_stage()`/`advance()` call site invokes it, no graph node
declares it, and it is not on the dashboard. Nothing consults a plan before a
real submission today. (2) It arbitrates an ADVISORY ranking, not a
reservation: it holds no lock and keeps no ledger of outstanding grants, so two
callers arbitrating the same instant against the same pool both see the same
capacity. A real reservation needs shared durable cross-project state that does
not exist here. (3) The capacity model is license free seats and queue slots
only -- compute, memory, disk and per-host limits have no producer this module
could read, and `JL/U` is parsed and reported but not yet enforced as a bound
(it is a PER-USER limit, and this module arbitrates per PROJECT). (4) No
production cross-job result exists, honestly: this repository is ONE project
with no multi-job farm, the same disclosure `cross_project_mining.py` already
makes about having no second project to mine. The mechanism is proven against
real preflight transcripts and a labelled farm fixture; it was not made to
"have fired" here by writing fabricated jobs into this project's real audit
trail.



<!-- S071: moved verbatim from CLAUDE.md original lines 4282-4355 (M4.6 CLAUDE Context Normalization) -->
## Generation Readiness Matrix (2026-09-06)

Spec section 211's GENERATION READINESS MATRIX is now a real, auto-generated artifact. The gap was
total and re-verified by negative grep before anything was written: `grep -rni
"generation.readiness"` matched only the specification's own text, and `grep -rn "GF-AT-"` matched
only `system_build_proof.py`'s GF-AT-28 comment. Section 211 prints a twenty-row table
(`Capability | Status | Existing Reuse | Evidence | Gap | Priority | Action`) with EVERY cell
empty, so "can this factory generate a subsystem environment from a spec, and a system environment
from subsystems?" had no machine-produced answer -- only prose an auditing session was trusted to
assemble by hand, which means two audits of the same project could disagree about the same facts.

`dv_harness/generation_readiness.py` is that artifact, and it is deliberately a SEPARATE module
from `golden_flow_readiness.py` rather than a second matrix bolted into it. The two answer
different questions from disjoint sources: section 47 asks "did this project's twenty GOLDEN FLOW
STAGES connect end-to-end with evidence" and reads stage RUN STATE (state.json, gate counts, LSF
jobs, coverage summaries, signoff records); section 211 asks "does this FACTORY have the generation
capability each rung of Flow A (spec -> subsystem UVM) and Flow B (subsystem UVM -> system-level
UVM) needs" and reads GENERATION ARTIFACTS (env.manifest.json's own layers, the protocol capability
registry, the subsystem environment registry, the real SYS-1..40 cross-subsystem analysis). Neither
table is derivable from the other, and a test asserts neither borrows the other's fact sources.
What IS shared is reused rather than re-minted: `subsystem_discovery`'s READY/PARTIAL/BLOCKED/
UNKNOWN readiness words AND its PRESENT/ABSENT/BLOCKED/UNKNOWN factor words, the real
`inference.next_best_action()` Gap -> Action engine, and `connectivity.render_markdown_table()`.

**Every row answers TWO questions, and Status is the STRICT worse of the two.** CAPABILITY -- does
the mechanism this row names exist and import in this harness? -- is decided by resolving the row's
own declared `fact_source` dotted paths through the import system (`assert_fact_sources_resolvable()`
proves all 62 of them), so a row whose backing mechanism has not landed renders BLOCKED naming the
missing path instead of a fabricated status. PROJECT EVIDENCE is what the row's real reader returned
over this root. The fold is strict worst-wins, not the softer mixing rule used to summarise many
rows: a present capability with no project input reads UNKNOWN, never PARTIAL, because GF-AT-28 says
UNKNOWN never becomes READY automatically and PARTIAL would read as progress that has not happened.

Where the rows land: rows 1-9 (Flow A) read env.manifest.json's OWN per-layer `status`/`reason` --
`dut_facts.rtl`, `dut_facts.registers`, `vip_config.vip_release`/`user_guide_refs`,
`env_topology.component_hierarchy`/`config_db_trace`/`testplan_correspondence` -- plus
`protocol_capability.capability_rows()` and, for Single-Test Proof, the registry's
`qualification_state` judged by the real `qualification.map_to_system_level_state()`. Rows 10-16 and
20 (Flow B) read `system_resource_inventory.real_cross_subsystem_findings()` (the same front door
the two real SYSTEM_LEVEL gates and the SoC composer cross-check against, so this table and those
verdicts cannot disagree), one `system_topology_analysis.analyze_system_topology()` document run
ONCE and read four ways, and `system_build_proof.subsystem_source_sets()`. Rows 17-19 sit on the
composer's deliberately-unimplemented boundary and PROBE it through the already-real
`system_scheduling_plan.probe_composer_boundary()`, which CALLS the three stubs and records that
they still raise -- so an implemented stub flips the row to PARTIAL ("boundary has moved") rather
than going unnoticed. `dv-harness generation-readiness [--json] [--no-deep]`, or `python -m
dv_harness.generation_readiness`; exit 2 unless every row is READY.

**Deliberately bounded, and stated rather than implied closed.** (1) It DECIDES, APPROVES and
ARBITRATES nothing: no stage is run, no gate script invoked, no build/regression/LSF job started
(the section 206 ladder is reported as having real sources, never RUN -- a readiness report that
starts a build is not read-only), and no governance state written. A real DRIVER_CONFLICT renders
BLOCKED, carries SYS-12's `preferred_model` through as text for a HUMAN, and says in the cell that
this harness does not pick a winner. SYS-39/40's stop before any real system command.txt, scenario
body or shared driver code is untouched. Two tests assert the report writes NOTHING into either an
empty project or a real two-subsystem one. (2) There is deliberately no stage gate: a gate passing
on a capability nobody exercised would be worse than none. (3) The Spec Parsing / Requirement IR row
has no canonical persisted artifact path in this repo, so its project axis is honestly UNKNOWN
rather than inferred from a stage status. (4) `--no-deep` skips the SYS-1..SYS-30 chain and the
Flow-B topology rows then say so as their recorded reason, never a guessed status.

Proven by `dv_harness_tests/test_generation_readiness.py` (28 tests). The headline test builds a
REAL two-subsystem project on disk -- reusing (importing, not copying) the fixture
`test_system_level_track_b_gate_crosscheck.py` already owns, whose `b_active=True` form puts two
ACTIVE AXI masters on ONE SoC CPU port -- and asserts the ownership row is BLOCKED off the REAL
SYS-9..SYS-14 analysis with human arbitration named, against a passive-second-driver negative
control that reads READY. Others assert the topology/command/virtual-sequencer rows match the REAL
`analyze_system_topology()` document field for field, that a demoted `qualification_state` in the
REAL registry flips the Single-Test Proof row, that env.manifest.json layers surface the
GENERATOR's own NOT_AVAILABLE reason text, that an unresolvable `fact_source` renders BLOCKED naming
it, that a raising probe still yields its mandatory row, and that both entry points run as real
subprocesses.



<!-- S082: moved verbatim from CLAUDE.md original lines 5111-5162 (M4.6 CLAUDE Context Normalization) -->
## Compile-Fix Loop: Fingerprinted NO_PROGRESS Stop (2026-09-06)

Section 93's rule -- "repeating the identical UVM_FATAL is not a useful retry" -- was already real and
wired in `loop_budget.py`'s `repeated_identical_failure_threshold` mechanism, but it applies to ANY
repeated failure signature, and nothing recognized a COMPILE/ELABORATION failure specifically as the
narrower circumstance a compile-fix retry loop needs: rerunning the SAME compile input against the SAME
toolchain and getting back the SAME normalized compile-error signature, N times running, is not merely a
repeated failure -- it is section 108/LOOP-AT-26's "artifact churn without verified gain", the real
NO_PROGRESS trigger `BREAKER_TRIGGERS` already names.

`COMPILE_FAILURE_RULE_ID` names the one `_TEXT_RULES` rule id `classify_failure()` already returns for a
compile/elaboration error (`sim_log_analysis.TRIAGE_CATEGORIES` was grepped before writing this and
confirmed to carry no compile category at all -- its markers are all POST-compile runtime signatures off
a sim.log, and a compile failure never reaches that log, so this rule id is the real and only
compile-stage signature this harness already produces from text). `is_compile_stage_failure()` answers
the narrower question from either of two real signatures, neither guessed: the classification's own rule
equaling `COMPILE_FAILURE_RULE_ID`, or a caller-supplied real Gate 1 `GateStatus` value (from
`connectivity.run_gate1_elaboration_check()` directly, or via the new `gate1_status_from_report()`, which
reuses `uvm_generator/bind_verification_lint.py`'s own `extract_status_block_from_markdown()` /
`extract_status_block_from_json()` report readers rather than a second parser) equaling
`GateStatus.FAIL.value`. `gate_rejected_evidence` -- the OTHER `_TEXT_RULES` rule this taxonomy also
files under DETERMINISTIC -- is a rejected gate-evidence block, not a compile error, and is never
recognized as one here.

`decide_compile_retry()` is wired onto the EXISTING `repeated_identical_failure_threshold` fingerprint
mechanism rather than a second one: it calls `decide_retry()` unchanged and only relabels the one case
that matters for a compile-stage failure specifically -- a `REPEATED_IDENTICAL_FAILURE` stop, if and only
if the failure is a real compile-stage one, becomes a compile-specific NO_PROGRESS stop. It is additive
by construction: a non-compile failure, a compile failure below the configured (and still off-by-default)
threshold, and a compile failure's OTHER stop reasons (`enforce_retry_policy`'s
`NON_RETRYABLE_FAILURE_TYPE`) all pass through with `decide_retry()`'s decision completely unchanged.
`BudgetEngine.decide_and_trip_compile_retry()` is the compile-retry call site: it calls
`decide_compile_retry()` and, when the decision is a compile-specific NO_PROGRESS stop, trips THIS
engine's real circuit breaker (section 91/`loop_budget.py`'s existing breaker, not a new one) so the
caller retrying a compile stage gets both the retry decision and the stop-new-actions consequence from one
call.

**No existing behavior changed.** Every non-compile failure, and every compile failure that has not
crossed the existing (off-by-default) `repeated_identical_failure_threshold`, produces byte-identical
decisions to before this change -- the full pre-existing `dv_harness_tests/test_loop_budget.py` suite was
re-run after this change and still passes in full.

Proven by 14 new tests added to `dv_harness_tests/test_loop_budget.py`: the compile-retry call site is
shown to trip the breaker as NO_PROGRESS on a real repeated compile signature, and shown to NEVER trip on
a repeated NON-compile failure or on a repeat that has not yet reached the threshold; `is_compile_stage_failure()`
is proven against both of its real recognition paths (the rule id and a real Gate 1 FAIL status) and
against the negative control (a non-compile DETERMINISTIC failure, e.g. `gate_rejected_evidence`, is never
recognized as a compile failure); `gate1_status_from_report()` is proven to reuse
`bind_verification_lint.py`'s own reader and to return `None` (never a guessed FAIL) on an absent or
broken report; and `decide_compile_retry()` is proven to relabel only the compile-repeat stop while
leaving a non-compile repeat stop, a below-threshold repeat, and a non-retryable-type stop all unchanged.


<!-- S086: moved verbatim from CLAUDE.md original lines 5366-5438 (M4.6 CLAUDE Context Normalization) -->
## Question Queue: Do-Not-Ask Enforcement + N-Option Question Builder (2026-09-06)

`dv_harness/question_queue.py` gained two additions, both scoped entirely inside that one module.

**(a) Do-not-ask enforcement.** `find_redundant_decision(prior_decision, context)` is the new
predicate deciding whether a live persisted decision for a `question_key` makes a FRESH ask of it
genuinely redundant -- and it deliberately mirrors `classify_tier()`'s own step-2 reasoning rather
than inventing a second rule that could drift from it. A HUMAN answer (`HUMAN_DECISION_SOURCE`) is
ALWAYS redundant regardless of the new ask's own context, restating `classify_tier()`'s "a human
answer on file DOES still win over a hard trigger" as a filing-time refusal. A Tier-2
auto-assumption (the new named constant `TIER2_AUTO_ASSUMPTION_SOURCE`, naming the literal
`"tier2_auto_assumption"` string `add_question()` already writes in several places) is redundant
ONLY when the new ask's own context trips NO new Tier-3 hard trigger -- deliberately NOT
unconditional, because treating a machine's own earlier guess as always-redundant would resurrect
review defect F3-a under the do-not-ask feature's own name (a tier2 guess permanently suppressing a
later, genuinely Tier-3-triggering re-ask of the same key).

`add_question()` gained an opt-in `enforce_do_not_ask: bool = False` parameter, the same
disclosed-default shape `require_tier`/`require_phy_boundary` already use elsewhere in this
codebase. When True and `find_redundant_decision()` finds a real match, `add_question()` raises the
new `DoNotAskError` (a `QuestionValidationError` subclass carrying `question_key` and the redundant
decision itself, so a caller can report exactly which decision made the ask unnecessary) BEFORE
persisting anything, instead of filing a duplicate. Default False keeps every existing caller's
behavior byte-identical: `repeat_question_rate` and every pre-existing test depend on a fresh record
being filed on every ask, and that stays true unless a caller opts in.

**(b) `build_multiple_choice_question()`** is the N >= 2 generalization of
`source_authority.escalate_conflict()`'s exactly-2-option shape, hosted here because this change's
scope is `question_queue.py` only (escalate_conflict itself lives in `source_authority.py`, outside
it -- see the disclosed residual below). It reuses this module's own `add_question()` /
`make_question_key()` exactly as `escalate_conflict` already does -- there is no second filing
mechanism -- and generalizes `assert_both_evidence_paths_present()` into
`assert_all_evidence_paths_present()`: every named candidate's `evidence_path` must appear verbatim
in the question text or an option's own label/rationale before anything is persisted, or
`QuestionValidationError` is raised naming exactly which paths are missing. Each candidate's
evidence path is folded into its own option's `rationale` the same unconditional way
`source_authority._option_for()` already does for its 2 sides. More candidates than the REAL current
`question.schema.json` `options.maxItems` (read live via `_schema_options_max_items()`, never a
second hardcoded "3") is REFUSED rather than truncated -- mirroring `escalate_conflict`'s own
"conflict with more than 3 sides is refused rather than truncated" rule, for the identical reason:
silently dropping a candidate would drop its evidence path with it. Filed with
`context={"affects_spec_intent": True, ...}` (`MULTIPLE_CHOICE_QUESTION_CONTEXT`), so
`classify_tier()` reaches Tier 3 (blocking) on its own ordinary rules rather than a tier being
asserted directly, and is idempotent on `question_key` -- an existing record for the same key is
returned as-is, the same discipline `escalate_conflict` already uses to avoid growing the queue on a
rerun over unchanged sources.

**Disclosed residual, not an oversight.** This task's scope was fixed to `question_queue.py` alone,
and a direct search confirmed `escalate_conflict`/`assert_both_evidence_paths_present` actually live
in `dv_harness/source_authority.py`, not here. So `assert_all_evidence_paths_present()` is a SECOND,
INDEPENDENT implementation of the identical rule, not a shared call into
`source_authority.assert_both_evidence_paths_present()` -- unifying the two for real needs an edit to
`source_authority.py` (either making `escalate_conflict` call this module's N=2 case, or pointing
both at one shared validator), which is outside this change. What IS checked, rather than merely
claimed, is that the two enforce the IDENTICAL rule: `test_assert_all_evidence_paths_present_
matches_source_authority_rule` drives both functions over the same conflict/options fixtures and
shows they accept and reject in lockstep -- a deliberate, disclosed duplication of one rule, not an
undisclosed drift into two diverging ones.

Proven by `dv_harness_tests/test_question_queue.py` (67 tests, up from 47 -- every pre-existing test
untouched and still green): `find_redundant_decision()`'s five cases including the F3-a-preserving
negative control (a tier2 guess must NOT suppress a later hard-trigger ask even with
`enforce_do_not_ask=True`); `add_question(enforce_do_not_ask=True)` refusing a duplicate after both a
human answer and a tier2 auto-assumption while still filing a genuine Tier-3 escalation over an
existing tier2 guess; `build_multiple_choice_question()`'s positive path (3 candidates, one Tier-3
blocking question, every evidence path cited), its negative controls (fewer than 2 candidates, a
candidate missing `label`/`evidence_path`, a recommendation not among the offered candidates, more
candidates than the real schema cap), its idempotent-refiling guarantee, and the direct proof that
`assert_all_evidence_paths_present()` itself catches a missing citation when option construction is
bypassed (unreachable through the public API today, since `build_multiple_choice_question` always
embeds every candidate's evidence path -- the same true-but-unreachable-through-the-public-API shape
`source_authority.escalate_conflict()`'s own guard already has).


<!-- S138: moved verbatim from CLAUDE.md original lines 8466-8510 (M4.6 CLAUDE Context Normalization) -->
## Command Error Taxonomy: Eleven Per-Dispatch Categories, Deliberately Distinct from `loop_budget.FailureType` (2026-09-06)

`dv_harness/command_error_taxonomy.py` classifies the real failure text produced by ONE command/task
dispatch (an exception message, a sim.log excerpt around the failing task) into one of eleven granular
categories with the matched evidence cited, or reports `UNCLASSIFIED` when nothing matches. Per the
Evidence Truth Rule, an unmatchable message is never forced into a named category -- `UNCLASSIFIED` is
the honest answer, not a missing feature.

**The task-layer vocabulary is read, not invented.** `.claude/skills/CORE/pattern-architecture/SKILL.md`
and `.claude/skills/CORE/branch-mapper/SKILL.md` already establish the real `block`/`branch_a0,branch_a1,...`/
`branch_fw`/`branch_b0,branch_b1,...` task-composition vocabulary this module operationalizes: a dispatch
stuck inside `branch_fw` (the per-port FW/event-service loop) is `FW_TIMEOUT`; stuck inside `branch_b*`
(the per-port VIP-driven test body, or naming a Synopsys `svt_`-prefixed VIP component -- the same prefix
convention `loop_budget.FailureType.VIP` already documents) is `VIP_TIMEOUT`; stuck inside `branch_a*`
(the per-port DUT+PHY init task, or naming the DUT/PHY generically with no branch label present) is
`DUT_TIMEOUT`. `BRANCH_OWNERSHIP_ERROR` operationalizes pattern-architecture section 3.1's own named trap
class -- "two independent task groups can hold conflicting locks on a shared bus sequencer" -- made
checkable from dispatch-failure text: two distinct task-layer families named together with a
lock/ownership/arbitration keyword. This module invents no interrupt-priority scheme, no arbitration
policy, and no timing value -- it only recognizes when dispatch-failure TEXT already names these real,
pre-established architecture terms.

**Reuse over reinvent.** `CHECK_FAILURE` and part of `TASK_ERROR` are decided by calling the existing,
real `sim_log_analysis.parse_sim_log()`/`classify_signatures()` triage engine -- this module never
re-derives a scoreboard/assertion/UVM_FATAL keyword list of its own.

**A different, more granular vocabulary than `loop_budget.FailureType` -- deliberately not merged.**
`loop_budget.FailureType` answers "why did this STAGE'S RETRY exhaust" (ten classes feeding a
retry-vs-stop decision across many dispatches at the stage-retry grain). This module answers a
finer-grained, different question: why did THIS ONE command/task dispatch fail, at the grain a single
command.txt task call fails at. Neither module imports the other, and
`assert_disjoint_from_loop_budget_failure_type()` keeps the two string vocabularies from silently
colliding as either grows; `assert_disjoint_from_verification_verdict_vocabulary()` likewise keeps this
module's eleven categories (plus `UNCLASSIFIED`) disjoint from `dv_harness.models.Status`.

**What this module does not do.** It classifies; it does not retry, does not stop a loop, does not spend
a budget, does not decide PASS/FAIL for a stage, and touches no human-approval gate -- a pure function of
the text it is given, no file I/O of its own beyond what `sim_log_analysis` already does internally, no
subprocess.

Proven by `dv_harness_tests/test_command_error_taxonomy.py` (29 tests): each of the eleven categories is
proven from its own real matching text, `UNCLASSIFIED` is proven on genuinely unmatchable text, both
disjointness asserts are proven to hold, and the `CHECK_FAILURE`/`TASK_ERROR` delegation into
`sim_log_analysis` is proven to reuse that engine's real classification rather than a second one.


<!-- S171: moved verbatim from CLAUDE.md original lines 10102-10115 (M4.6 CLAUDE Context Normalization) -->
## AMBA Performance Classification: Saturation / Bottleneck-Candidate / Anomaly / Regression-Delta (2026-09-06)

`amba_performance_calculator.py` already does the raw PERFORMANCE ARITHMETIC (bandwidth, throughput, latency percentiles, utilization, the hard functional-correctness-outranks-performance precedence). Nothing in this repo turned those numbers into a CLASSIFICATION: is a port/path actually SATURATED, what is the leading bottleneck CANDIDATE (not a confirmed root cause), does an observed sample DEVIATE from a real historical baseline, and did a metric IMPROVE/REGRESS/stay UNCHANGED between two measured periods. `dv_harness/amba_performance_classification.py` is that classification layer, built under the same three hard rules `amba_performance_calculator.py` already enforces in code (never a docstring promise): a threshold/target/baseline is never invented (`NOT_APPLICABLE` when absent), an unprovable metric yields `UNKNOWN` (never a computed-looking number), and functional correctness always outranks a performance PASS.

**Four classifiers, each requiring AT LEAST TWO correlated real caller-supplied metrics -- never one metric alone.** `classify_saturation()` requires utilization sitting at/above a caller-declared fraction of a caller-declared max ceiling ALONGSIDE a real rising-latency or rising-stall trend signal; either metric alone reports `UNKNOWN` (never a guessed SATURATED/NOT_SATURATED), and the two metrics DISAGREEING (one signals saturation, the other does not) reports `INDETERMINATE`, never silently resolved in either direction. Asserting a rising trend as `True` with no cited evidence is refused outright (`PerformanceClassificationError`), never silently accepted. `identify_bottleneck_candidate()` builds a structured `{hypothesis, evidence, confidence, gap, next_best_action}` record -- matching this project's existing Hypothesis -> Evidence -> Confidence -> Gap -> Next-Best-Action discipline (see `inference.py` for the pattern; deliberately NOT imported, since that module's `score_confidence()` counts generic corroborating evidence for an arbitrary claim, and this domain needs its own correlated-metric-count-based confidence derivation instead) -- and refuses (raises) to construct one from fewer than 2 real, non-empty, independently-cited correlated evidence entries: a hypothesis resting on one metric is never reported as a candidate. `detect_anomaly()` compares a real observed sample against a real caller-supplied baseline (a historical range, or a mean/stddev distribution plus a caller-declared deviation threshold); an absent baseline is `NOT_APPLICABLE` (a baseline is never fabricated from the observation alone), and a missing observation is `UNKNOWN` regardless of baseline availability. `compute_regression_delta()` compares two real measured samples/periods for one named metric and reports IMPROVED/REGRESSED/UNCHANGED/INCONCLUSIVE -- INCONCLUSIVE, never a fabricated percentage, whenever the two samples declare different units, declare different measurement windows, or the baseline is zero (a percent-change against zero is mathematically undefined, not silently reported as 0% or as an arbitrary large number).

**Reuse, not reinvention, of the functional-correctness precedence.** `decide_overall_performance_verdict()` does not reimplement rule (c) a second time -- it imports and calls `amba_performance_calculator.decide_overall_verdict()` directly, mapping this module's own regression-delta verdict onto that function's `performance_verdict` parameter (IMPROVED/UNCHANGED become a performance PASS, REGRESSED becomes a performance FAIL, INCONCLUSIVE/UNKNOWN/absent are passed through as "no performance verdict was evaluated"). There is exactly one place in this project that decides "does functional correctness outrank a performance result", and this module calls it rather than duplicating it: a functionally-FAILed transaction whose own regression delta reports IMPROVED still resolves to an overall FAIL.

**Jain's fairness index, included because this batch's source document calls for a fairness/QoS-inversion check.** `compute_jains_fairness_index()` is the real, well-known one-line formula (`J = (sum(x_i))**2 / (n * sum(x_i**2))`, Jain/Chiu/Hawe 1984) over a real per-requester allocation/throughput map. It refuses to compute -- reports `UNKNOWN`, never a value silently computed over the subset that happened to report -- the instant ANY declared requester's value is absent, and reports `UNKNOWN` rather than a fabricated `1.0` on the genuinely undefined all-zero (0/0) case; a single requester is honestly `NOT_APPLICABLE` (fairness across one requester is not a meaningful question).

**Deliberately bounded, and stated rather than implied closed.** This module reads no FSDB/waveform file, monitors no live signal, generates no traffic, and runs no simulation -- all explicitly out of scope for this batch, since this harness has no live simulator to validate any of that against; it imports nothing from `dv_harness` beyond `amba_performance_calculator`'s reused precedence function and its own status-token constants, plus `models.Status` for a vocabulary-collision check. It decides, approves, and arbitrates nothing beyond its own classification: no gate, no approval, no build/regression/LSF submission. **2026-09-07 correction**: the "no CLI verb was added" clause above is now stale -- see "AMBA Performance Modules: Standalone Front Doors + `dv-harness` CLI Wiring" below, which closes that gap for this module and its two siblings.

Proven by `dv_harness_tests/test_amba_performance_classification.py` (54 tests): the core positive path for all four classifiers plus the fairness index; the required negative controls -- a single metric never classifies saturation either way, no declared ceiling is `NOT_APPLICABLE`, a missing observation is `UNKNOWN`, a single-evidence-item bottleneck candidate is refused, an absent baseline anomaly check is `NOT_APPLICABLE`, a zero-baseline regression delta is `INCONCLUSIVE` rather than a fabricated percentage, incomplete per-requester fairness data is refused rather than silently computed over the partial set, and an all-zero fairness input is `UNKNOWN` rather than a fabricated perfect score; and the headline functional-correctness-outranks-performance proof, driving a real `REGRESSION_IMPROVED` performance result alongside a functional FAIL to a confirmed overall FAIL through the reused `amba_performance_calculator.decide_overall_verdict()`.


<!-- S186: moved verbatim from CLAUDE.md original lines 10567-10584 (M4.6 CLAUDE Context Normalization) -->
## Intra-Project Root-Cause Clustering: Differently-Worded Signatures, Same Underlying Bug (2026-09-07)

`capability_evolution.repeated_unresolved_failure_patterns()` already groups this project's own `job_failure` records by EXACT `evidence_db.signature_key()` -- the right tool for "the same failure, recorded twice" (a retry, a re-run against one commit). It is the WRONG tool for "two agents worded the SAME real root cause differently": `symptom="link training timeout on lane 0"` and `symptom="link training timeout observed on lane zero"` hash to two entirely different keys and are never grouped, even though a human reading both would recognise them instantly. `cross_project_mining.py` answers an adjacent but genuinely different question -- the SAME exact signature_key recurring across SEVERAL PROJECTS' stores -- and is explicitly out of scope here.

`dv_harness/intra_project_root_cause_clustering.py` is the missing layer BETWEEN those two: within ONE project's own store, it clusters DISTINCT signature_key groups whose own real `symptom`/`root_cause_hint`/`terminal_signature` text is similar enough that a human should be asked whether they are one root cause under two names.

**REUSE, not reinvention, on every axis.** The exact-match grouping (which records share one `signature_key`) is `evidence_db.signature_key()`, imported. "Which records were INDEPENDENT observations" is `capability_evolution._run_identity()`, imported -- three retries against one commit stay one observation here too, exactly as it does one layer up. "Is this signature already closed" is `capability_evolution.failure_resolution_claims()`/`resolved_failure_claim_texts()`, imported -- the same exact-equality join against a real `verified_fix` record's own `root_cause`/`symptoms` text, never a second, fuzzier definition of "resolved". The tokenizer is `memory._tok`, imported as `_tokenize` -- the exact stopword-aware tokenizer `memory_dedup.py` and `memory_vault.py` already reuse the same way, not a third copy. Evidence is read through the shared `MemoryStore.find()`, and `cross_project_mining.has_memory_store()` is checked BEFORE ever constructing a `MemoryStore` -- that constructor `mkdir()`s the five-tier tree and writes an empty `index.json`, so asking "does this project have anything to cluster" must never itself create the store it is asking about.

**Clustering rule, stated plainly.** Two DISTINCT signature_key groups are merged into one cluster only when BOTH hold: (1) both declare the SAME real, non-empty `protocol` (normalized, case-insensitive) -- a different protocol is a different subsystem, not the same root cause reworded, and is never bridged by incidental text overlap; (2) the Jaccard token overlap of their own `symptom` + `root_cause_hint` + `terminal_signature` text is at or above `min_similarity` (default `DEFAULT_MIN_SIMILARITY = 0.5`, the same order of magnitude as `spec_intelligence.DUPLICATE_SIMILARITY_LOW_THRESHOLD` -- a disclosed heuristic a caller may override, never a semantic/embedding model, since none exists in this codebase and inventing one would be exactly the unverifiable machinery the Evidence Truth Rule forbids). A group missing a protocol, or carrying too little descriptive text (`MIN_TOKENS_FOR_COMPARISON`) to compare honestly, is never silently paired with anything -- it is reported, by name, as `ineligible_signature_groups` with the real reason (`MISSING_PROTOCOL` / `INSUFFICIENT_DESCRIPTIVE_TEXT`). The pairwise scan is O(n^2) over eligible groups; above `MAX_CLUSTER_SCAN_SIZE = 300` the scan is SKIPPED and disclosed (`STATUS_SCAN_SKIPPED_TOO_LARGE`) rather than run unbounded, mirroring `spec_intelligence.MAX_DEDUP_SCAN_SIZE`'s own precedent -- every eligible group is still reported as an unclustered single, never silently dropped.

**Clustering is a SUGGESTION, and only ever a suggestion -- it never mutates a memory record.** This module is a pure read: it never calls `MemoryStore.add()`/`MemoryGC.confirm()`/`retract()`/`supersede()`, never merges two records into one, and writes no memory record of any tier. A returned cluster carries the whole real evidence basis it was built from -- member signature keys, real `memory_ids`, the real pairwise similarity score and shared tokens that connected them, a union (never a sum -- a run appearing under two differently-worded signatures is deduplicated, not double-counted) of independent run identities across members, and each member's own real `resolved_by_verified_fix` status -- so a human/caller re-derives the conclusion by hand rather than trusting an opaque cluster id, and decides for themselves whether to act (e.g. by hand-writing one `verified_fix` covering both claim texts, or recording a `MemoryGC.supersede()` decision). Per-cluster `resolution_status` (`CLUSTER_ALL_OPEN`/`CLUSTER_PARTIALLY_RESOLVED`/`CLUSTER_ALL_RESOLVED`) is where the module's real value shows up most directly: a `verified_fix` closed under ONE clustered signature's exact wording, worded slightly differently from a sibling signature's own text, would never join the two under `capability_evolution`'s own exact-text `failure_resolution_claims()` join -- clustering surfaces that they are the same bug and that the still-open, differently-worded instance may already be fixed.

A cluster's `cluster_id` (`RCC-<hash>`) is content-derived from its sorted member signature keys, so a recurring cluster across re-runs is recognisable as "the same suggestion again" rather than a fresh random id each time. The module's own status vocabulary (`CLUSTERS_FOUND`/`NO_CLUSTERS_FOUND`/`INSUFFICIENT_EVIDENCE`/`SCAN_SKIPPED_TOO_LARGE`, plus the three resolution-status values) is asserted disjoint from `dv_harness.models.Status` at import time, checked with a monkeypatch test proving the guard has real detection power rather than merely never firing by accident.

Ad hoc front door only: `python -m dv_harness.intra_project_root_cause_clustering --root <dir> [--min-similarity F] [--json]` (exit 0 clean/no finding, 1 a real cluster was suggested, 2 insufficient evidence / scan skipped / a usage error) -- no `dv-harness` CLI verb and no `gates.py`/`cli.py` edit, the same disclosed choice several sibling same-day modules in this codebase already make for a new standalone module while those files are large and under concurrent use. There is deliberately no stage gate: a clustering suggestion is an input to a human's memory-hygiene review, never a substitute for one, and this module decides, approves and arbitrates nothing.

Proven by `dv_harness_tests/test_intra_project_root_cause_clustering.py` (20 tests), every fixture built through the REAL production write path (`memory_router.route_and_store()` + `memory_vault.build_failure_signature()`, the same convention `test_cross_project_mining.py` already established) -- never a hand-typed store file. Negative controls carry the detection power: a different protocol is never bridged by identical text; dissimilar text under one protocol stays unclustered; a missing-protocol group and a too-thin-text group are each reported ineligible by name rather than silently paired or dropped; a byte-identical signature dict stays ONE exact-match group, proving this module starts one level above `capability_evolution`'s own exact grouping rather than duplicating it; the same real `job_id` recorded under two differently-worded signatures is correctly union-deduplicated to one independent run rather than double-counted; and a byte-level snapshot proves the store is untouched by a clustering pass. All three resolution-status values are driven from real `verified_fix` records. The scan-skip guard, markdown rendering, all three `execute_verb()` exit codes, and a real `python -m` subprocess round trip are each separately proven.


<!-- S204: moved verbatim from CLAUDE.md original lines 11564-11575 (M4.6 CLAUDE Context Normalization) -->
## RCA_G1 Fan-Out: Genuine Cross-Branch CONTRADICTION Detection (2026-09-07)

`engine.py`'s RCA_JOIN synthesis point (`_write_blackboard_from_evidence()`) already builds a real, graph-derived `contributing_agents` list for the `rca_evidence_fusion` Blackboard topic -- which RCA_G1 branches (RCA_RTL_EVIDENCE / RCA_LOG_EVIDENCE / RCA_VIP_SPEC_EVIDENCE) really PASSed and really wrote their own topic, never trusted from RCA_JOIN's own agent text. Until now that was the only cross-branch signal: two branches finding nothing (uncorroborated) and two branches actively disagreeing about the root cause (contradictory) both silently produced the exact same `contributing_agents` entry, and `multi_agent_consensus_count` (`_root_cause_confidence_inputs()`) only ever counted CORROBORATION -- it had no way to see a genuine disagreement at all.

`DVHarness._detect_rca_branch_contradictions()` closes that gap, additively, at the exact same synthesis point, and reuses the identical anti-fabrication discipline `contributing_agents` already established: every claim it compares is read straight off a branch's OWN real Blackboard topic (`self.blackboard.read(branch_stage)["value"]["evidence"]["root_cause_evidence_gate"]["root_cause"]`), never from RCA_JOIN's own text. RCA_RTL_EVIDENCE/RCA_LOG_EVIDENCE/RCA_VIP_SPEC_EVIDENCE are deliberately NOT gated on `root_cause_evidence_gate` (gates.py's own comment: gating a branch on it would push it to invent the very cross-domain conclusion RCA_JOIN exists to make) -- so this reads the block only when a branch agent happened to emit one, and never requires it.

**Genuinely contradictory, not merely uncorroborated.** A branch that cites nothing is silently excluded from comparison -- the honest UNCORROBORATED case, never flagged. Two (or more) branches that DO cite a real, non-empty `root_cause` are compared by exact text (case/whitespace-normalized only, never fuzzy, the same "never fuzzy" discipline this project's other evidence-matching code already applies): identical claims across branches is corroboration; two or more textually DISTINCT claims is a real, cited `contradiction_detected: true`. The new `branch_contradiction_flag` field lands on the SAME `rca_evidence_fusion` topic entry alongside `contributing_agents`, carrying `conflicting_claims` (every branch's own stage/agent/root_cause, only when a contradiction was actually found) and a `basis` string naming which case applies.

**Strictly additive -- proven, not merely claimed.** `multi_agent_consensus_count`/`_root_cause_confidence_inputs()` (the existing consensus-count accumulation `score_confidence()` reads) and the pre-existing `contributing_agents` list are both asserted byte-identical in the new tests whether or not a contradiction is detected -- a genuine disagreement between two independently-dispatched, blind-to-each-other specialist agents neither inflates nor deflates the existing consensus count; it is recorded as a wholly separate, honest signal a human/RE_AUDIT reviewer can now actually see.

Proven end to end (never mocking the mechanism under test) by 4 new tests appended to `dv_harness_tests/test_rca_multi_agent_fanout.py`, each driving the REAL `DVHarness` through FAILURE_RECOVERY -> the real `ThreadPoolExecutor`-backed RCA_G1 fan-out -> a real gate-verified RCA_JOIN PASS: a genuine two-branch contradiction is flagged and cites both real claims; two branches independently citing the SAME real root cause are never flagged; a single citing branch (the other two silent) is the honest uncorroborated case and is never flagged; and the pre-existing generic-placeholder fixture every OTHER test in the file already uses (no branch ever emits a `root_cause_evidence_gate` block at all) produces an honest, present, non-fabricated `contradiction_detected: false` rather than a missing field.


<!-- S209: moved verbatim from CLAUDE.md original lines 11784-11806 (M4.6 CLAUDE Context Normalization) -->
## Loop Persistence / Resume / Stale Detection: a Real STALE Detector (2026-09-06, section 97)

`loop_contract.py`'s own header docstring already names `STALE` as one of the two states (alongside `RESUMING`) section 86 adds "for persistent sessions", `LEGAL_LOOP_TRANSITIONS` already carries five real edges into it (from READY/RUNNING/VERIFYING/CONVERGING/STOPPED), and `RESUMABLE_LOOP_STATES` already lists it as a real stop condition a human/resume path can leave. What did not exist, confirmed by direct search before writing a line of this: `derive_loop_state()` took no `stale` input at all, and `loop_telemetry.LOOP_STATE_WITHOUT_EVENT_REASON[LoopState.STALE.value]` said outright "Section 97's stale detection... has no producer in this harness." A loop session could resume against a `git_sha` from three real commits ago, or a `last_transition` timestamp from a week-old run, and be reported CONVERGING/READY/RUNNING/STOPPED exactly as if it had just happened -- the same unearned-freshness gap `golden_scenario.py`'s own capsule freshness check exists to close one test at a time, left open at the whole-session level.

`dv_harness/loop_stale_detection.py` is the detector, and it is two real signals, reusing this harness's OWN existing evidence producers rather than inventing a third:

- **TIME-BASED** -- this session's own last REAL event (`loop_telemetry.read_loop_telemetry()`'s per-session `last_event_at` when a `run_id` is supplied; otherwise `state.json`'s own real `last_transition.at` -- the same "just transitioned" record `dashboard.py`'s Last-Transition banner already reads -- falling back to the latest per-stage `started_at`/`finished_at`) compared against a DECLARED staleness window (`config.json`'s `policy.loop_stale_after_seconds`, or this module's own documented `DEFAULT_STALE_AFTER_SECONDS` when a project has not declared one -- the window is always named alongside its source, never presented as a project-specific measurement it is not).
- **ENVIRONMENT-MOVED** -- `state.json`'s recorded `git_sha` no longer matches the project's real current HEAD, by a REAL `git diff --name-only` through `change_impact.changed_files()` -- the exact function `golden_scenario.evaluate_freshness()` and `signoff_export.evaluate_freeze_invalidation()` already reuse for the identical "did the design move" question one layer down -- classified through the SAME `change_impact.classify_risk()` HIGH/MEDIUM/LOW ladder those two callers already use. A LOW-risk-only diff (docs, `.dv-harness`/`.claude` bookkeeping) does not call the session stale; a HIGH/MEDIUM one does.

**Worst-wins, and "we could not check" is never read as clean.** `detect_loop_staleness()` reports STALE the instant either real signal fires; absent that, an UNKNOWN signal (no real event evidence at all, no recorded SHA, no git) outranks a clean NOT_STALE -- the same GF-AT-28 "an unresolved Critical UNKNOWN must never silently become the good answer" discipline `platform_health.py`/`golden_flow_readiness.py` already apply one domain over, applied here to a single loop session's own freshness. The mandated negative control is a bare project with no `state.json`, no `config.json`, and no git repository at all: BOTH signals are genuinely `UNKNOWN`, and the combined verdict is `UNKNOWN` -- never a fabricated `NOT_STALE`.

**Read-only, and it mints nothing.** Both `state.json` and `config.json` are read with a plain, tolerant `json.loads()` -- never `storage.StateStore.load()`/`config.load_config()`, both of which CREATE those files for a project that has never run, the same reasoning `golden_flow_readiness.py`/`signoff_export.read_signoff_stage_status()` already record for themselves. A bare project reports honest `UNKNOWN` signals and gains no `.dv-harness/` tree from being asked.

**Wired into the real state machine, not left standalone.** `loop_contract.derive_loop_state()` gained a `stale: bool = False` keyword, checked LAST -- after TAKEOVER/PAUSE/the retry-family budget branch/`loop_done`/plateau/oscillation, i.e. after every other real finding -- and scoped to exactly `loop_contract.STALE_ELIGIBLE_BASE_STATES`, a set DERIVED from `LEGAL_LOOP_TRANSITIONS` itself (never hand-typed a second time) rather than assumed to be the same five states this section's opening paragraph names. That placement and scope mean staleness can never re-route or hide a genuine TAKEOVER/PAUSE/BUDGET_EXHAUSTED/BLOCKED/HUMAN_GATE/PLATEAU/OSCILLATING finding, or a terminal SUCCESS/FAILED/CANCELLED one -- those are real facts about what already happened, and staleness says nothing that would make any of them less true. `observe_verification_closure_loop()` gained a `staleness: Optional[dict] = None` keyword (this module's own report, carried onto the observation's `evidence`/`derived_from`/`note` exactly as `convergence` already is), and `observe_all()` computes one best-effort -- never crashing the caller on a failed git/read -- and passes it through. Every existing caller of `derive_loop_state()`/`observe_verification_closure_loop()`/`observe_all()` that does not pass the new keyword is byte-for-byte unchanged, proven directly (`test_derive_loop_state_stale_false_is_byte_identical_to_before`).

`loop_telemetry.LOOP_STATE_WITHOUT_EVENT_REASON[LoopState.STALE.value]` was corrected rather than left stale itself: STALE still names no section-108 EVENT (that fixed, closed nineteen-name vocabulary is untouched and unwidened -- `emit()` still refuses anything outside it), but the STATE now has a real producer, and the reason text says so.

Front door: `python -m dv_harness.loop_stale_detection {window|detect}` (`execute_verb()`, the same shared convention `loop_contract`/`loop_budget`/`loop_telemetry` already follow); exit 0 `NOT_STALE`, 1 `STALE`, 2 `UNKNOWN`. No `dv-harness` CLI verb was added and `cli.py`/`gates.py` were not touched, matching several very recent same-day additions' own disclosed choice when those two files are under concurrent edit pressure.

**Deliberately bounded, and stated rather than implied closed.** (1) It decides nothing beyond the two signals and their fold: no build, job, approval, or stage gate references it, and there is deliberately no `STAGE_GATES` entry -- a `STALE` verdict is a fact `derive_loop_state()`/a human resuming a session can act on, never a substitute for a resume decision. (2) It has no `run_id` auto-discovery of its own beyond `loop_telemetry`'s own per-session fold; a caller wanting a specific session's own last-event evidence must supply that session's `run_id`. (3) The declared staleness window is a single project-wide `policy.loop_stale_after_seconds`, not a per-loop-type or per-stage window -- section 97 names one staleness concept and this module implements exactly that one, not a family of them. (4) `RESUMING`'s own detection (confirming a resumed session's SHA/environment/tool versions still match before trusting its earlier evidence -- the sibling half of section 86's "for persistent sessions" clause) is unchanged and remains `loop_telemetry.previous_session_summary()`'s own real, working mechanism; this module closes STALE only.

Proven by `dv_harness_tests/test_loop_stale_detection.py` (35 tests, `python -m pytest dv_harness_tests/test_loop_stale_detection.py -q` -> `35 passed`) against REAL machinery throughout: a REAL throwaway git repository with real commits (environment-moved staleness is derived from a genuine `git diff` between two real SHAs, exactly as `golden_scenario.py`'s own central proof does one layer down -- committing a real HIGH-risk RTL change makes a previously-clean recorded SHA read STALE, naming the real changed file and its real classified risk; a LOW-risk-only doc commit does not), and real plain `state.json`/`config.json` files on disk. The mandated negative control (`test_combined_unknown_never_fabricated_as_not_stale_on_a_bare_project`) proves a bare project with no state, no config, and no git at all reports `UNKNOWN` -- never a fabricated `NOT_STALE` -- and mints no `.dv-harness/` tree in the process. The `derive_loop_state()` wiring is proven both ways: `stale=True` genuinely overrides every one of the five eligible base states, and is proven to NEVER override BUDGET_EXHAUSTED/RETRY_WAIT/BLOCKED/HUMAN_GATE/OSCILLATING/SUCCESS or a TAKEOVER/PAUSE-forced state, with `STALE_ELIGIBLE_BASE_STATES` itself asserted equal to a live derivation off `LEGAL_LOOP_TRANSITIONS` so the two can never silently drift apart. Both real CLI verbs (`window`, `detect`) are driven as real subprocesses across all three exit codes. The pre-existing `dv_harness_tests/test_loop_contract.py` (50 tests) and `dv_harness_tests/test_loop_telemetry.py` (37 + 8 tests) suites were re-run in full alongside this one; both carry one pre-existing, unrelated failure (`COMMAND_PATTERN` reaching `GATE_FAIL` instead of `PASS` because a concurrently-added `command_generation_gate.py` is now registered in that stage's `STAGE_GATES` with no matching evidence in those tests' own fixtures) that reproduces identically with this change's edits fully reverted (`git stash`) -- confirmed pre-existing and out of this task's own scope, since `gates.py` is explicitly off-limits here.


<!-- S259: moved verbatim from CLAUDE.md original lines 15270-15349 (M4.6 CLAUDE Context Normalization) -->
## Root-Cause Ontology + Failure-Signature Normalization (2026-09-06)

Two related, narrow mechanisms, one module: a fixed root-cause CATEGORY ontology that
classifies a CLOSED Engineering-Memory `root_cause`/`verified_fix`/`debug_lesson`
record's own category for CROSS-PROJECT AGGREGATION, and a canonical
failure-signature normalizer. Confirmed by direct grep before building: no
`root_cause_categ`/`RCA_CATEGORY`/`RootCauseCategory` mechanism existed anywhere, and
this project's two existing failure taxonomies both classify *in-flight failure text*
at a different, finer grain -- `command_error_taxonomy.py` (why did ONE
command/task dispatch fail) and `system_failure_taxonomy.py` (what KIND of
SYSTEM/multi-subsystem-composition failure occurred). Neither ever asks "once this
finding was closed and verified, what KIND of component actually owned the fix" --
the question `dv_harness/rca_ontology.py` answers, over a RECORD that has already
reached closure, not over in-flight symptom text.

**Eleven categories, cited-evidence phrase classification, same house style as its
two neighbours.** `ROOT_CAUSE_CATEGORIES` (`KNOWN_LIMITATION_ACCEPTED_RISK`,
`FLAKY_NONDETERMINISTIC_BEHAVIOR`, `TOOLCHAIN_INFRASTRUCTURE_DEFECT`,
`CONFIGURATION_ERROR`, `SPEC_REQUIREMENT_DEFECT`, `COVERAGE_MODEL_DEFECT`,
`CHECKER_SCOREBOARD_DEFECT`, `STIMULUS_SEQUENCE_DEFECT`,
`VIP_DEFECT_OR_MISCONFIGURATION`, `TESTBENCH_ENVIRONMENT_DEFECT`, `DUT_RTL_DEFECT`)
plus the honest `UNCLASSIFIED` fallback -- never forced into a named category when a
record's text matches no recognised phrase. `assert_disjoint_from_command_error_
taxonomy()` / `assert_disjoint_from_system_failure_taxonomy()` / `assert_no_
verification_verdict_vocabulary()` all run at import (against the real, imported
`command_error_taxonomy.CATEGORIES` / `system_failure_taxonomy.FAILURE_CATEGORIES` /
`models.Status` -- not a hand-transcribed copy, since none of the three is claimed by
a concurrently-running batch) and prove none of the vocabularies collide.

**"CLOSED" is REUSED, never re-derived.** `closure_status()` calls
`memory_router.route_memory(record) == "ENGINEERING_MEMORY"` -- the SAME
kind-is-root-cause-shaped-and-declared-verified check every real write path already
uses -- and then `memory_router.engineering_admission_gate(record, root=root)`, the
real, already-enforced three-gate bar (evidence, HIGH/CONFIRMED confidence, a
reusable claim). A record failing either is honestly `NOT_ROOT_CAUSE_RECORD` /
`NOT_YET_CLOSED` and is **never** categorized or signature-keyed --
`classify_closed_root_cause_record()` returns `category=None`/`signature_key=None`
for both, proven by dedicated negative-control tests, per Core Operating Rules'
"Any current root cause must be revalidated with current evidence" and this
project's own Evidence Truth Rule.

**The canonical failure-signature normalizer reuses, never reinvents, "same
failure".** `canonical_failure_signature()` runs `sim_log_analysis.
normalize_failure_signature()` over free-text fields first (the SAME normalization
`loop_budget.py`'s circuit breaker already keys its `REPEATED_IDENTICAL_FAILURE`
trigger on), then `memory_vault.build_failure_signature()` (the ONE canonical
signature-dict shape `engine.py`/`lsf_client.py`/`loop_budget.py`/
`capability_evolution.py`/`cross_project_mining.py`/`verification_strategy.py`
already build), then `evidence_db.signature_key()` (the ONE stable hash those same
callers already group/accumulate `occurrence_count` by). Proven by direct comparison
(`test_canonical_failure_signature_matches_direct_composition_of_reused_functions`)
against manually chaining the three real functions -- byte-identical, not merely
plausible. `canonical_signature_for_record()` extracts those inputs off a real
root_cause/verified_fix record's own already-written fields.
`aggregate_root_cause_categories()` composes closure + category + canonical
signature over a batch of records into per-category counts and per-signature-key
groups, counting only `CLOSED_ELIGIBLE` records -- excluded records are still
reported, with their real reasons, never silently dropped from the total.

**Deliberately bounded.** This module never mines a cross-project store itself
(`cross_project_mining.py`'s already-real, separate mechanism owns "how many
PROJECTS independently confirm one signature"); it never writes a memory record,
promotes a tier, runs a build/regression/LSF job, or touches any human-approval
gate. There is no `dv-harness` CLI verb and no `gates.py`/`cli.py` edit (both files
are explicitly avoided per this batch's own guidance) -- the front door is
`python -m dv_harness.rca_ontology categories|classify --records <file.json>
[--root <dir>]`.

Proven by `dv_harness_tests/test_rca_ontology.py` (42 tests): the positive path for
all eleven categories plus `UNCLASSIFIED`-on-no-match and priority-ordering
negative controls; `closure_status()` driven through all three real outcomes
(`NOT_ROOT_CAUSE_RECORD` for wrong kind/unverified, `NOT_YET_CLOSED` naming the real
`engineering_admission_gate()` reason codes for an unevidenced low-confidence guess,
`CLOSED_ELIGIBLE` for a fully gate-verified record); the two never-categorized
negative controls; the canonical-signature reuse proof and its
cosmetic-variance-collapse proof; the aggregation report's honest exclusion
accounting and signature-grouping; all three vocabulary-disjointness guards plus a
mutation-style test proving they have real detection power; and the standalone CLI
driven as real subprocesses across all three exit codes (0/1/2).


<!-- S276: moved verbatim from CLAUDE.md original lines 16364-16442 (M4.6 CLAUDE Context Normalization) -->
## Cross-Loop Coupling: Coverage-Closure Stall -> Auto-Filed Capability Candidate (2026-09-06)

Master prompt section 64's second gap-detection source -- COVERAGE_HOLE, already a real
`capability_evolution_candidate.schema.json` `trigger_type` enum member -- had no detector,
confirmed by direct grep before building: `capability_evolution.py` auto-files a candidate only
from REPEATED FAILURES (`repeated_unresolved_failure_patterns()` /
`file_repeated_failure_candidate()`, see "Cross-Loop Coupling: Repeated Failure -> Auto-Filed
Capability Candidate" above), and `loop_convergence.classify_loop_convergence()`'s own real
PLATEAU verdict -- reading the REAL evidence database via `trend_analysis.daily_rollup()`, per
"Convergence, Plateau and Oscillation Detection" above -- had no caller that ever turned a stalled
coverage-closure loop into a capability question. A project's coverage curve could sit flat cycle
after cycle, `classify_loop_convergence()` could correctly report PLATEAU every single time, and
nothing would ever raise a candidate from it.

`dv_harness/coverage_stall_capability_discovery.py` is that sibling detector, built as a SEPARATE
module rather than an edit to `capability_evolution.py`: that file is 3000+ lines and, at build
time, was one of dozens of files being actively created/edited minutes apart by other agents in
this same batch (confirmed by directory mtimes) -- the same low-collision-but-give-your-own-module-
a-distinct-name posture this project's own governance already states, applied one level up to a
shared central file rather than a naming collision. Nothing in it is reimplemented: `coverage_
stall_pattern()` calls the REAL `classify_loop_convergence()` and returns the real trigger fact only
on a real PLATEAU verdict (every other verdict, including the honest UNKNOWN a project with no
series/evidence reports, returns `None` -- never promoted into a fabricated plateau finding); `build_
coverage_stall_candidate()` / `file_coverage_stall_candidate()` / `file_candidates_for_coverage_
stall()` are built entirely on `capability_evolution`'s own real public primitives --
`build_candidate()` (recommendation DERIVED by `decide_recommendation()`, confidence recomputed
through the real `inference.score_confidence()`), `persist_candidate()` (the SAME
`capability_evolution_candidates` Blackboard topic and Working Memory audit trail every other
candidate uses), `read_candidate()`, `IllegalPromotionTransitionError`, `L5_SEARCH_SLOTS`, and the
real `_auto_filed_search_slot()` helper for the six honest NOT-SEARCHED slots -- with the identical
three-outcome filing discipline (`DISCOVERED` / `ALREADY_ON_FILE_UNCHANGED` /
`ALREADY_BEYOND_DISCOVERED`) `file_repeated_failure_candidate()` already established.

**Same three structural walls, unweakened.** (1) `file_coverage_stall_candidate()` never calls
`transition()` and refuses to persist anything not at DISCOVERED. (2) It performs NO repository
search -- all six `existing_*` slots carry `search_conclusive: false` with an honest `search_basis`
quoting the real next-best-action out of `RESEARCH_GAP_ACTION_CATALOG`, so `overlap_status` and
`recommendation` are DERIVED to UNKNOWN and the schema's own `allOf` pins `current_status` to
DISCOVERED/EVIDENCE_GATHERING/REJECTED. (3) `assert_legal_transition()`, `assert_human_approval()`'s
real `ControlPlane` check, `HumanApprovalRequiredError` and `ProductionWriteNotAuthorizedError` are
untouched and uncalled from this module -- not one line of the human-approval boundary is
referenced, let alone weakened.

A stable, content-derived identity (`_stall_key()`, over the metric name and this project's own
configured plateau thresholds -- deliberately NOT the transient per-cycle `flat_run_samples`/window
values, which change every day the plateau continues) means a plateau re-detected across cycles
lands on the SAME candidate and accumulates evidence rather than forking a duplicate, mirroring
`mint_candidate_id()`'s own content-derived design one level up.

Proven by `dv_harness_tests/test_coverage_stall_capability_discovery.py` (12 tests,
`python -m pytest dv_harness_tests/test_coverage_stall_capability_discovery.py -q` -> `12 passed`):
a real CONVERGING series and a too-short series both correctly file nothing; a bare project with no
evidence at all reports the honest UNKNOWN loop_convergence itself produces and files nothing --
the required negative control that this coupling refuses to fabricate a plateau finding when
evidence is absent; a real PLATEAU series files a real, persisted DISCOVERED candidate whose
`overlap_status`/`recommendation` are UNKNOWN and whose six search slots are honestly unsearched;
confidence is proven recomputed (never trusted) from its own stored inputs; re-filing an unchanged
plateau does not grow the Working Memory audit trail; a candidate a human has already advanced past
DISCOVERED is left alone rather than dragged back; the auto-filed candidate is proven unable to
reach `HUMAN_APPROVED` or a production write; and one full end-to-end pass drives the REAL
`dashboard.append_coverage_history_sample()` production write path into a REAL DuckDB evidence
store, through `daily_rollup()`, to a real PLATEAU verdict, to a real persisted candidate. The
pre-existing `test_capability_evolution_auto_discovery.py` (23 tests) and `test_loop_convergence.py`
(53 tests) suites were re-run unchanged alongside it (88 tests total, all passing), confirming this
addition changes neither `capability_evolution.py` nor `loop_convergence.py` -- both are only
imported.

**Disclosed residual**: like its repeated-failure sibling, this closes DISCOVERY only. An auto-filed
coverage-stall candidate parks at DISCOVERED with UNKNOWN overlap/recommendation until a human runs
`dv-harness research` (or a real `research-architect` pass) to perform the six current-L5 searches;
nothing in the engine performs them. This module is also REACHED, not WIRED: no `run_stage()`/
`advance()` call site or engine hook invokes `file_candidates_for_coverage_stall()` yet -- a future
integration would call it the same way `engine._file_capability_evolution_candidates_from_repeated_
failures()` calls its sibling, at a point where a real PLATEAU verdict is already being computed
(e.g. beside `engine._classify_loop_convergence_for_telemetry()`'s own retry-exhaustion call site) --
and it lives as a standalone module beside `capability_evolution.py` rather than as a literal sibling
function inside it, a deliberate choice given that file's size and this batch's concurrent-edit
pressure at build time rather than a claim that folding it in later would be wrong.


<!-- S294: moved verbatim from CLAUDE.md original lines 17459-17530 (M4.6 CLAUDE Context Normalization) -->
## Build/Remote/LSF Intake Resolution: `build_remote_lsf_intake.py` (2026-09-06)

Section 31 asks for intake facts specific to build/remote-execution/LSF readiness -- "is a build
environment reachable, is LSF configured" -- resolved as additional `intake_state.py`-shaped field
records. REUSE OVER REINVENT, checked before writing this section: a repo-wide grep for
`build_remote_lsf`/`BuildRemoteLsf`/`remote_lsf_intake` matched nothing, and neither
`intake_state.py`, `intake_baseline.py`, nor `verification_intake_contract.py` reference
`preflight.py` at all -- a confirmed real gap, distinct from `intake_state.py`'s own `build_env`
category (which reads `connectivity.run_gate1_elaboration_check()` -- "did the generated testbench
actually ELABORATE", an *elaboration*-time fact) and answering the earlier, narrower question this
section names: before any elaboration is attempted, is the BUILD/SUBMISSION environment itself even
usable -- is the target host reachable, is a real transport (local or the persistent remote relay)
actually confirmed, is the LSF queue Open:Active, is the EDA license server up with headroom, is the
workdir there and writable, is there enough disk, are the required EDA env vars set.

`dv_harness/build_remote_lsf_intake.py` invents NO new probe anywhere: every fact is read straight
off `preflight.py`'s own REAL, already-tested checks (`preflight.run_preflight()`'s six
`CheckOutcome`s: `eda_license`, `lsf_queue_health`, `host_reachability`, `disk_space`, `workdir`,
`eda_env_vars`) and `preflight.resolve_transport()`'s own real, evidence-based `TransportDecision`.
The module performs zero subprocess calls, zero network I/O and zero license/queue/relay probing of
its own -- it only maps an ALREADY-PRODUCED `preflight.PreflightResult`/`preflight.TransportDecision`
onto `intake_state.IntakeFieldRecord`s in a new `"build_remote_lsf"` category (`fields_from_preflight()`),
and composes those records into an existing `intake_state.IntakeState` (`merge_into_intake_state()`) --
`intake_state.IntakeFieldRecord`/`IntakeFieldStatus`/`IntakeState` are imported and used verbatim, never
re-typed.

**Status mapping, per real `CheckOutcome.status`**: PASS -> AUTO_RESOLVED (HIGH); FAIL -> BLOCKED
(HIGH), mirroring `preflight.py`'s own "did not pass -> BLOCKED" rule; SKIP -> MISSING (UNKNOWN) --
a real, deliberate "this check did not run" is absence of a result, never a caller's own declared
exemption, so it is never silently promoted to NOT_APPLICABLE (per `intake_state.py`'s own module
docstring, which reserves NOT_APPLICABLE for an explicit caller declaration); an unrecognized status
string -> UNKNOWN (evidence supplied but inconclusive); no `CheckOutcome` supplied at all -> MISSING.
`remote_transport_available` is sourced from `preflight.TransportDecision` instead of a `CheckOutcome`:
a resolved `local`/`remote_relay` transport that is `available` -> AUTO_RESOLVED; an EXPLICIT `off`
request -> NOT_APPLICABLE (the real caller-declared "out of scope" exception); a malformed transport
request (an unrecognized transport string, via the decision's own `evidence["unknown_transport"]`
key) -> BLOCKED; anything else (`auto` probed and found nothing usable) -> MISSING, never read as a
confirmed absence.

`BuildRemoteLsfReadiness`/`evaluate_build_remote_lsf_readiness()` is the category's own worst-wins
verdict, computed via `intake_state.IntakeState.category_status()` (reused, never re-implemented):
`ready` is True iff every field's status is in `intake_state.NON_BLOCKING_STATUSES`
(AUTO_RESOLVED/USER_CONFIRMED/NOT_APPLICABLE) -- the identical non-blocking vocabulary
`evaluate_uvm_generation_ready()` uses one layer up.

**Deliberately bounded, and stated rather than implied closed.** This module JOINS and REPORTS,
exactly like `intake_state.py` itself: it runs no probe, files no question, writes no
state/blackboard/approval record, and holds no stage gate of its own. It also does NOT edit
`intake_state.py` -- `BLOCKING_CATEGORIES`/`evaluate_uvm_generation_ready()` are left untouched, so
the new `"build_remote_lsf"` category does not (yet) block `UVM_GENERATION_READY` by itself; a caller
who wants that composes `merge_into_intake_state()`'s result into whatever gate ultimately runs
`evaluate_uvm_generation_ready()` and reads this category separately via
`evaluate_build_remote_lsf_readiness()`/`IntakeState.category_status("build_remote_lsf")`. This
mirrors the "REACHED, not WIRED" disclosure many sibling modules in this codebase already carry:
`intake_state.py` is a live, extensively-used core file, and adding a category to its own hard-coded
blocking list is a separate, deliberate policy decision out of this item's own scope. There is also
no `dv-harness` CLI verb and no `cli.py`/`gates.py` edit -- the front door is the Python API
(`fields_from_preflight()`/`merge_into_intake_state()`/`evaluate_build_remote_lsf_readiness()`).

Proven by `dv_harness_tests/test_build_remote_lsf_intake.py` (18 tests, re-run by this integration
pass: `python -m pytest dv_harness_tests/test_build_remote_lsf_intake.py -q` -> `18 passed`) against
REAL `preflight.run_preflight()`-shaped `PreflightResult`/`CheckOutcome`/`TransportDecision` objects
(both object and `to_dict()`-dict input shapes accepted identically): a full real all-PASS preflight
run, a real FAIL, and the required negative controls proving the module refuses to fabricate an
answer when evidence is absent -- no `PreflightResult`/`TransportDecision` at all leaves every field
MISSING with confidence UNKNOWN and `value=None`; a real SKIP stays MISSING rather than being
silently promoted to NOT_APPLICABLE; an unrecognized check-status string reads UNKNOWN rather than
being rounded to PASS/FAIL; a malformed `preflight_result` shape (an int, or a dict missing its
`"checks"` key) raises `TypeError` rather than silently producing an empty or wrong record set.
`TestCategoryScoping` confirms the worst-wins composite fold: a single BLOCKED/MISSING/UNKNOWN field
fails the whole category regardless of how many sibling fields resolved cleanly.


<!-- S324: moved verbatim from CLAUDE.md original lines 19665-19734 (M4.6 CLAUDE Context Normalization) -->
## Question Rephrasing / Clarification Loop: `request_clarification()` (2026-09-07)

`question_queue.py` already files a Tier-3 question exactly once (`add_question()`), with a fixed
question text and 2-3 pre-researched options, but had no mechanism for a human who does not
understand an already-filed question to signal that and get back a clearer restatement. A
repo-wide search for `rephrase`/`clarif`/`reword` before this change confirmed no such mechanism
existed anywhere in this codebase (no concurrent work had already added it either).

`request_clarification(store, question_id, *, requested_by=None, reason=None, now=None,
record=True)` is that missing, purely additive extension. It is deliberately **not** a second
filing mechanism: it never calls `add_question()`, never mints a new Q-ID or `question_key`, and
never changes a question's tier/status/blocking. It only

1. **re-renders an EXISTING record** -- read via `store.get_question()`, the store's own existing
   lookup, never a second one -- into a clearer, more scannable structure built entirely from
   fields that record already carries: `options[].rationale` (labeled "evidence, per option"),
   `context_path`, `tier_reason` (translated from `classify_tier()`'s own small, closed,
   machine-oriented vocabulary into plain English via a fixed lookup table,
   `_explain_tier_reason()`/`_TIER_REASON_TRIGGER_EXPLANATIONS` -- content that never reached a
   human before, since `build_escalation_package()`'s 9-field view omits `tier_reason` and
   `exemption` entirely), the `exemption` citation when present, and
   `assumption_if_unanswered`/`answer` phrased per the record's real tier; and
2. **records, best-effort, that a human asked for one** -- a real audit entry appended to a new
   sibling file, `QuestionQueueStore.clarifications_path`
   (`.dv-harness/question_queue/clarifications.json`), written through this module's own
   `_atomic_write_json()`/`_read_json()` primitives (the same ones `_save_questions()`/
   `_save_decisions()` already use) -- never a new persistence mechanism, and **never a write to
   `questions.json` itself**: `question.schema.json`'s `additionalProperties: false` on the
   persisted question record stays exactly as strict as before.

**"Simpler phrasing" is honestly bounded, per the Evidence Truth Rule.** This does not run any
kind of semantic paraphrase over the question's own free-text sentence -- there is no safe way to
do that without risking silently changing what the question actually asks. What it does is
translate `classify_tier()`'s own literal `tier_reason` tokens (`hard_trigger:
affects_pass_fail_verdict`, `blast_radius_exceeds_safe_assume_bound:...`, the `;overrides_prior_
non_human_decision` / `;covered_by_active_exemption:<id>` suffixes) into plain-English sentences
via a fixed lookup, and lay every option's own pre-researched rationale out explicitly. An
unrecognized `tier_reason` token (this lookup table drifting out of sync with `classify_tier()`)
is surfaced verbatim rather than dropped or guessed at -- the negative control this change is
proven against.

`list_clarification_requests(store, *, question_id=None)` is the read-only reader over that
sibling file (mints nothing on an absent file); `render_clarification_markdown(clarification)`
renders one `request_clarification()` result the same "one labeled section per block" way
`render_escalation_package_markdown()`/`_render_decisions_md()` already do elsewhere in this
module.

Proven by 18 new tests appended to `dv_harness_tests/test_question_queue.py` (93 total, all
passing at the time of writing -- this file has since grown further under concurrent multi-agent
editing, `python -m pytest dv_harness_tests/test_question_queue.py -q` -> `157 passed` as of this
integration pass, including these 18): the real package/plain-summary grounding; unknown-id
`KeyError`; per-option evidence citation; the two required negative controls (a bare-label option
with no rationale on file is reported "(no additional rationale on file)", never a fabricated one;
an unrecognized future `tier_reason` token is surfaced verbatim, never dropped or guessed at); a
byte-identical `questions.json` before and after (proving no second question is filed and the
record is never mutated); Tier-1/2/3- specific phrasing (self-resolved / machine-guess-not-human-
answer / the real fallback assumption); the exemption citation (via a monkeypatched
`find_exemption()`); multiple simultaneous hard triggers each explained; `record=False` writing
nothing to `clarifications.json`; `record=True` persisting and `list_clarification_requests()`
reading it back (including filtering by `question_id`); repeated requests appending rather than
overwriting; the default `requested_by` value; and markdown rendering. The full pre-existing
question-queue ecosystem was re-run in full alongside it -- confirmed clean.

**Deliberately bounded, and stated rather than implied closed.** This does not (and structurally
cannot) rewrite the question's own sentence with a genuine paraphrase -- only its already-known
surrounding context is restructured and its internal-vocabulary fields are translated. It is
REACHED, not WIRED: there is no `dv-harness` CLI verb and no dashboard/GUI surface calling it yet
-- a caller (a human via a future CLI/GUI, or an agent handling a "I don't understand" signal)
invokes `request_clarification()` directly today.


<!-- S347: moved verbatim from CLAUDE.md original lines 21176-21236 (M4.6 CLAUDE Context Normalization) -->
## AMBA Performance Trend View: Regression-Delta + Anomaly Detection Across Recorded Periods (2026-09-07)

`dashboard.py` already had two real AMBA-performance cards -- AMBA Bottleneck Analysis
(`identify_bottleneck_candidate()`) and AMBA Per-Port Performance Center
(`aggregate_port_performance()`) -- confirmed by grep before writing anything, per REUSE OVER
REINVENT. Neither ever ran `amba_performance_classification.py`'s two remaining classifiers,
`compute_regression_delta()`/`detect_anomaly()`, across a project's own RECORDED SEQUENCE of
periods, and nothing anywhere rendered a trend a human could read. `dashboard_amba_performance_
trend_view` closes exactly that gap, additively, following the sibling cards' own template
byte-for-byte: a thin JSON-file front door onto the two real functions, never a second
trend-arithmetic engine.

**Data shape.** `.dv-harness/amba/performance_trend.json`:
`{"metrics": {"<metric_name>": {"lower_is_better"?, "improvement_threshold_percent"?,
"periods": [{"period_id", "value"?, "window"?, "unit"?, "baseline_min"?, "baseline_max"?,
"baseline_mean"?, "baseline_stddev"?, "deviation_threshold_stddev"?}, ...]}}}`. Each consecutive
PAIR of one metric's own declared `periods` (caller's own declared order -- never re-sorted by a
guessed date) is exactly `compute_regression_delta()`'s own real keyword arguments; every
individual period is exactly `detect_anomaly()`'s own real keyword arguments.

**Honest absence, never a fabricated trend line -- the item's own required wording, literal.** A
metric with zero recorded periods reports `trend_status: "NOT_AVAILABLE"` ("no recorded periods
declared for this metric -- no history exists to trend, never fabricated"); a metric with exactly
ONE recorded period reports `trend_status: "INCONCLUSIVE"` ("only one recorded period declared --
compute_regression_delta() requires two real measured periods to compare") --
`compute_regression_delta()` is never called with a fabricated second sample. `detect_anomaly()`
still runs normally for a single-period metric (it needs only one observed value plus a baseline),
so a metric can be trend-INCONCLUSIVE while still reporting real per-period anomaly results. A
metric/period declaration this module refuses to build (a malformed shape, a missing
`period_id`) is surfaced under `rejected`, never silently dropped and never turned into a
fabricated metric.

Wired: `GET /api/amba-performance-trend` (with a `?trend=` path override mirroring the sibling
cards' own `?samples=`/`?candidates=` convention), a new "AMBA Performance Trend" card + table in
the served HTML, and `loadAmbaPerfTrend()`/`renderAmbaPerfTrend()` JS wired into the real
page-load sequence alongside the sibling AMBA cards -- never a card left unreachable from any page
load, the PARTIALLY_WIRED shape this project's Methodology Consolidation Rule forbids.

**Disclosed**: `CLAUDE_L5_WEB_CONTROL_PLANE_MASTER.md` (the theme document cited for this item)
does not exist anywhere in this checkout (confirmed by a repo-wide find), matching several other
sections' own honest disclosure of a master-prompt document this repo does not carry. The design
is grounded instead in the real, already-shipped sibling AMBA cards' own established pattern.

**Read-only by design**, same as every AMBA card: this renders real period-over-period
comparisons a human reads -- nothing here decides a root cause, runs a build/simulation, or writes
a verification verdict. This harness owns no live simulator; every value/period shown is
caller-supplied evidence, never estimated.

Proven by `dv_harness_tests/test_dashboard_amba_performance_trend_view.py` (12 tests, driven
against the real dashboard server over real HTTP, re-run fresh for this integration pass:
`python -m pytest dv_harness_tests/test_dashboard_amba_performance_trend_view.py -q` -> `12
passed`): the honest empty-state (no file), zero-period -> NOT_AVAILABLE, one-period -> INCONCLUSIVE
(with anomaly detection still running), a real 2- and 3-period regression-delta computation
(including the consecutive-pair-not-first-to-last proof), a real cross-unit INCONCLUSIVE delta
matching `compute_regression_delta()`'s own reason text, a real ANOMALY_DETECTED vs NO_ANOMALY pair
against a declared baseline, the required negative control (an observed value with no declared
baseline reports the real NOT_APPLICABLE, word-matched against `detect_anomaly()`'s own "a
baseline is never fabricated" reason -- never a fabricated verdict), rejected-declaration handling,
malformed-file handling (a real error reason, never a 500), the `?trend=` override, and the
card-is-served-and-wired check.


