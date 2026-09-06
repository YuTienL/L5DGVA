# AI Agent Harness L5 - Project Instructions

## Core Operating Rules
- Graph is the global workflow authority.
- Blackboard stores current verification truth.
- Verification Memory stores historical verified engineering knowledge.
- Claude project/native memory may store stable project instructions, conventions, workflow rules and user preferences.
- Memory is prior knowledge, not current evidence.
- Any current root cause must be revalidated with current evidence.
- Human Override is always valid.
- Same regression batch must use the same source/build/config identity.
- LSF DONE is not equal to DV PASS.
- One submitted LSF job = one isolated Job Agent context.
- Important DUT/PHY/Register/VIP changes require Multi-Agent evidence acquisition plus independent synthesis.
- All actionable findings must close before Final Deep Audit.
- Any process/method/workflow validated in a session must be consolidated into the Harness's permanent engine/agent/skill assets, not left as one-off conversation state.
- Once a real deficiency/weakness/gap is confirmed by evidence (e.g. an audit pass), it must be closed by launching multi-agent implementation work on all currently-known confirmed gaps together, not queued one-at-a-time waiting for individual re-asks.


## Evidence Truth Rule

CLAUDE.md is project guidance, not verification evidence.

Never treat any statement in this file as proof of a current DUT behavior, bug, root cause or pass/fail condition.

Before accepting an engineering conclusion:
- inspect the current RTL/source when relevant,
- inspect/measure current waveform/FSDB when relevant,
- analyze current sim.log/checker/assertion evidence,
- verify current register/programming state when relevant.

If CLAUDE.md conflicts with current evidence, current evidence wins and this file must be updated.


## Engineering Memory Policy (2026-09-03)

Concrete before/during/after mechanics for the 5-tier Memory system
(`dv_harness/memory.py`, routed by `dv_harness/memory_router.py`, mirrored
into the DV-Knowledge Vault by `dv_harness/memory_vault.py` -- see
`docs/MEMORY_ARCHITECTURE.md`). This operationalizes the Core Operating
Rules' "Memory is prior knowledge, not current evidence" and the Evidence
Truth Rule above; it does not restate them.

**Before debugging**: Search relevant Project Memory and Engineering Memory
for the current protocol/scope/symptom before forming a first hypothesis
(`python -m dv_harness.memory_cli search --protocol <p> --text <symptom>`,
or the `memory-retrieval` skill). Any hit is a candidate hypothesis to rank
higher, never an accepted root cause -- validate it against current
RTL/VIP/sim.log/waveform evidence exactly as the Evidence Truth Rule
requires, and as `memory-confidence-gate` keeps historical-memory
confidence and current root-cause-evidence confidence from being conflated
into one number.

**During debugging**: Maintain Hypothesis -> Evidence -> Confidence -> Gap ->
Next-Best-Action for every open failure (`dv_harness.inference.score_confidence()`
/ `identify_gap()` / `next_best_action()` -- see debug-agent.md's "v20
Autonomous Inference"). Each stage transition is a real, persisted Working
Memory record (`memory_router.route_memory()` routes `kind="react_reasoning_step"`
there), not only conversation state.

**After verified PASS**: Record root cause, evidence, fix, verification, and
confidence together as one Engineering Memory record (`kind` one of
`root_cause`/`verified_fix`/`debug_lesson`, `verified: true`), then evaluate
promotion:
- Engineering -> Organizational happens ONLY through
  `memory_router.promote_to_organizational()`, never a direct write. It
  requires all three: the qualitative CLOSED/VERIFIED + single PASS +
  regression PASS/NOT_REQUIRED + re-audit CLEAN gate (`memory-consolidation`
  skill), a HIGH `inference.score_confidence()` result, and
  `confirmation_count >= ORGANIZATIONAL_MIN_CONFIRMATIONS` (2, i.e. a second
  independent run re-deriving the same root_cause/protocol -- not the same
  run reported twice). That third gate became reachable from the REAL
  writers only on 2026-09-04: the confirm-on-re-derivation dedup keys on
  (protocol, root_cause), but no gate's `JUDGMENT_FIELDS` ever judged
  `protocol`, so engine.py's two Engineering-tier writers wrote it as None
  on 30 of 31 real records and every re-derivation minted a fresh record
  instead of a confirmation -- the tier was unreachable by its own intended
  organic route, and only a test calling `MemoryGC.confirm()` directly had
  ever cleared it. Both writers now key on this run's canonical
  `protocol_router.resolve_protocol()` value, and
  `MemoryConsolidator.from_closed_finding()` confirms rather than duplicates
  on a re-derived closed finding. See `docs/MEMORY_ARCHITECTURE.md` and
  `dv_harness_tests/test_engineering_confirmation_accumulation.py`, which
  proves it end-to-end through real `run_stage()` gate-verified PASSes.
  Since 2026-09-04 "ONLY through" is enforced at the
  write boundary rather than trusted from callers:
  `memory_router.organizational_admission_gate()` re-reads the promotion
  provenance (`source_engineering_memory_id`) off the durable store -- the
  source record must be ACTIVE, engineering-tier, gate-validated, and carry
  an EARNED on-disk `confirmation_count` -- and demotes anything else to
  Working Memory with `organizational_admission_rejected`, before it can
  reach the shared Knowledge Center or mint an approval commit.
- A record failing any one gate stays at Engineering tier (or lower). Do not
  re-word the qualitative gate's inputs to force a pass.
- Reaching the Engineering tier at all is itself gated
  (`memory_router.engineering_admission_gate()`, 2026-09-03): a
  `verified: true` flag alone is not enough. The record must ALSO carry real
  `evidence` (or a gate-validated `verification` block), `confidence`
  HIGH/CONFIRMED (or that same gate-validated block), and a reusable claim
  (`root_cause`/`fix`/`lesson`, with `reusable` not `false`). A record
  failing any of those is written to Working Memory instead, carrying
  `engineering_admission_rejected` — this is the "Never promote an unverified
  hypothesis straight to Engineering" rule below as enforced code, not
  trusted prose. Do not pad an `evidence` field to clear it.

**Never**:
- Store secrets/passwords/tokens/credentials in any memory tier or vault
  note -- `memory_router.route_memory()` already hard-`REJECT`s any record
  whose `kind` is `credential`/`password`/`token`/`secret`; this is enforced
  code, not policy prose.
- Store giant logs or raw FSDB content in a memory record or vault note --
  cite a path/offset/signature only, per the Waveform Dump User Gate and
  Simulation Observability Default above.
- Promote an unverified hypothesis straight to Engineering or Organizational
  Memory -- it belongs in Working Memory (or Blackboard, for current-run
  state) until it clears verification.

**Debug-flow / regression / git-integration mechanics (2026-09-03,
obsidian-memory-debugflow, Workstream 3)**: `dv_harness.engine.DVHarness.
run_stage()`'s FAILURE_RECOVERY/RE_AUDIT stages, and `dv_harness.lsf_client
._write_job_tier_memory_on_terminal_reconcile()` (real UVM_ERROR/UVM_FATAL/
abnormal-termination signal), both call the same shared interface --
`dv_harness.memory_vault.build_failure_signature()` /
`search_related_memory_for_debug()` -- to surface Vault matches as prior
evidence BEFORE a debug attempt (never an assumed root cause: 不得直接假設
previous root cause == current root cause). AFTER a debug attempt: FAIL/
PARTIAL updates Job Memory only, no promotion; a RE_AUDIT PASS records
symptom/root_cause/evidence/fix/verification/confidence/git SHA/test/result
and always triggers (not always succeeds) the `promote_to_organizational()`
evaluation. Vault git commits (`memory.git_enabled`, opt-in) fire only on a
verified Job result, a Project Memory update, an Engineering Memory
promotion, or an Organizational Memory approval -- never on a Working Memory
update -- with message format `memory(<protocol>): <short description>`; a
real commit's SHA is written back onto the underlying JSON MemoryStore
record as `knowledge_commit_sha`, alongside its existing `rtl_sha`/`tb_sha`.
See `.work/obsidian-memory-debugflow-report.md` for full detail.

**Knowledge deduplication runs on the AUTOMATIC write path too (2026-09-04)**:
`memory_dedup.classify_note_candidate()` had exactly one caller, the manual
`dv-harness memory add` verb. The path that actually populates this project's
vault -- `memory_router._maybe_write_vault_note()`, which every real
ENGINEERING_MEMORY/ORGANIZATIONAL_MEMORY promotion goes through -- decided
create-vs-update from `memory_id` identity alone, so a second record with a new
id but the same root cause minted a second note (the spec's own
`USB3_LFPS_issue1/issue2/issue3` shape), and all 9 notes then on disk had
reached the vault without passing the gate once. The gate now runs on the
CREATE path: NEW creates a note, RELATED creates one AND writes real
`[[WikiLink]]`s to what it overlaps, DUPLICATE/UPDATE_EXISTING create nothing
and instead APPEND one recurrence line (carrying the real `memory_id`, and for
UPDATE_EXISTING the differing configuration/symptom) to the matched note's
`Related Knowledge` -- no existing section is ever rewritten. The corpus is
restricted to the candidate's OWN tier, because an Engineering ->
Organizational promotion is the same knowledge written again BY DESIGN and a
tier-blind gate would make the Organizational tier unwritable; Job/Project
notes are never gated at all. A dedup failure never blocks the write. See
`docs/MEMORY_ARCHITECTURE.md` and
`dv_harness_tests/test_memory_dedup_write_path.py`.


# AI Agent Harness L5 Canonical Identity

This directory is the canonical AI Agent Harness L5 baseline.
Do not rely on legacy version labels in older reference markdown files.

Core policy:
- Graph is global workflow authority.
- Blackboard is current truth.
- Memory is prior knowledge.
- Current evidence wins.
- Human Override is always valid.


## Execution Mode Gate

Every workflow must begin by explicitly declaring whether it is:
- LOCAL_ANALYSIS: 「這個是純本地讀檔分析（不碰伺服器、不跑 VCS）。」
- REMOTE_EXECUTION: 「這個需要連伺服器/跑模擬。」

Mixed workflows must be split into phases and the mode must be re-declared at every phase transition.
Local static findings must never be described as runtime/simulation evidence.


## SSH/Remote Transport Connection Intake

When a workflow declares REMOTE_EXECUTION and requires SSH/network transport to a Linux DV server
(real server credentials are involved), first ask the user whether SSH/network transport should be
established this session. Do not assume or silently attempt a connection.

If the user confirms, request these required fields before attempting any connection:
- user account
- password
- vc machine name (e.g. vchost-a, vchost-b)
- ssh machine name (e.g. host-a, host-b)
- DV Agent's working path/directory on the Linux server

The password must never be written into any evidence block, gate payload, state file, log, or
long-term/native memory. It is used only at the moment of the actual interactive connection and must
never be persisted by the harness — consistent with Remote Control Mode below ("Never expose SSH
private keys or credentials to Web/App or long-term memory"). The other four fields (account, vc
machine name, ssh machine name, working path) may be recorded as connection evidence since they are
not secrets by themselves.


## Remote Linux Execution (Persistent Relay)

`remote_hop.py`, `remote_relay.py`, `remote_exec.py`, and `source_identity.py` live in
`tools/remote/` within this `v50` project (not at the repo/project root).

Once a Linux DV server session has been established this session per the SSH/Remote Transport
Connection Intake gate above (user confirmed, relay started by the user in their own terminal), do
not ask the user to manually run and paste back individual Linux commands. Use:

  python tools/remote/remote_exec.py "<command>"

Check readiness first with `python tools/remote/remote_exec.py --status`. If READY, issue commands
directly. If DOWN, run `python tools/remote/remote_exec.py --reconnect`; if that reports the relay
cannot self-reauthenticate, ask the user to restart it in their own terminal (never embed VCPW in
any Claude-issued command) and stop until they confirm it is back up.

This does not remove the SSH/Remote Transport Connection Intake gate itself — establishing or
re-establishing a relay for the first time in a session still requires that confirmation. It only
removes the per-command manual-paste fallback once a relay is already confirmed READY.

`remote_relay.py` (which actually performs the login) must never be invoked from a Claude Code tool
call, including to test its own error paths — not even when the invocation doesn't type a password
into the command text. A persistent OS-level environment variable can supply required credentials
silently, defeating a "missing env vars" safety check without any password ever appearing in the
command itself (confirmed real incident, 2026-08-31 — see
`remote-linux-execution-bridge/SKILL.md`'s corresponding drift note). Test `remote_relay.py`'s logic
via unit tests against its pure `RelayServer.handle_request()` function, never via a live `--start`.

**2026-09-03 amendment (explicit user decision, single-user machine)**: on this specific machine,
confirmed single-user by the project owner, the user has explicitly decided to relax the prohibition
above: when `remote_exec.py --status`/`--reconnect` reports the relay is down mid-session, Claude
Code MAY automatically source a local, never-committed credential script (e.g. `replay.csh`, kept
outside version control and outside any path Claude reads or echoes) and invoke
`remote_relay.py --start` to reconnect, without asking the user each time. This is a deliberate
override of the 2026-08-31 incident's original blanket prohibition — the user judged that a
single-user machine reduces credential-exposure risk enough to accept fully autonomous reconnect in
exchange for not being interrupted. This amendment covers only mid-session RECONNECTION; the
SSH/Remote Transport Connection Intake gate above (asking before the FIRST connection of a session)
is unchanged and still applies.

Even under this amendment:
1. The password itself must still never be printed, echoed, quoted, or written into any evidence
   block, log, gate payload, or memory record.
2. Claude may source and invoke the credential script, but must never read or print the script's
   own contents.
3. This amendment is scoped to this machine/project only. If this harness is ever deployed to a
   shared or multi-user environment, this decision must be explicitly re-confirmed before it still
   applies there.

Source identity (PC vs. Linux) is verified per-project: git SHA comparison where a git remote exists
between PC and Linux, or the md5sum-based `SOURCE_ID` token (`source_identity.py`, see
`remote-linux-execution-bridge`) where it does not — never skipped outright.

Never request or print passwords, tokens, or credentials in any `remote_exec.py` invocation or
output.


## Background Job/Log Monitor Auto-Start

There is no Python code path that fires automatically the moment
REMOTE_EXECUTION_REQUIRED is declared -- that declaration is agent-supplied
evidence (an `execution_mode_validator` block embedded in the agent's own
message text), not an engine event with a hookable call site. "Automatic"
here means the same thing it means for the SSH/Remote Transport Connection
Intake gate above: a required action the agent takes as part of following
this protocol, not something the engine does on its own.

Once REMOTE_EXECUTION_REQUIRED has been declared and any needed SSH/Remote
Transport Connection Intake has completed, run:

    dv-harness lsf-watch-start --vcuser <account>

before submitting or expecting visibility into any LSF job this session.
This starts (or confirms already-running) a detached background process
that discovers every live job under that account, reconciles/analyzes any
job this harness has a registered `JobState` for, and maintains the
`regression.list` safety net (see `apply_verdict_to_file()` in
`dv_harness/uvm_generator/regression_list_manager.py`) for jobs that bypass
the generated environment's own Makefile-native `RECORD=1` mechanism. It is
a no-op if a watcher is already running for this project (tracked via a PID
file). Stop it with `dv-harness lsf-watch-stop` on a clean session end, or
when execution mode transitions back to `PURE_LOCAL_READ_ANALYSIS`.

**Cadence.** The watcher is a fixed-interval polling loop, not event-driven:
`regression_reporter.main()` runs one reconciliation cycle then sleeps
`--interval-minutes`. The default is **5 minutes**
(`regression_reporter.DEFAULT_INTERVAL_MINUTES`, the cadence the 2026-09-01
sim-output-layout design doc committed to). `self_check_list.md` #41 requires
job/simulation-log state to be re-confirmed at least every **10 minutes**
(`regression_reporter.SPEC_MAX_INTERVAL_MINUTES`), so 5 is inside the ceiling.
A slower `--interval-minutes` is still permitted but never silent:
`interval_compliance()` makes `lsf-watch-start` print a stderr warning and the
watcher log its real cadence on the first line.


## Waveform Dump User Gate

Before any waveform-enabled simulation, ask the user to confirm dump scope and dump level/depth.
Prefer minimum sufficient waveform based on the current failure cone.
Do not silently default to full-chip/full-depth dumping.

**Enforced against a real human answer, not a self-attested string (2026-09-04).** This rule had a
real gate since 2026-08-28 (`tools/verification_flow/focused_wave_debug_window_gate.py`, mandatory
on `WAVE_ANALYSIS` and `FAILURE_RECOVERY`), but it only required
`dump_scope_confirmed.confirmed_by` to be a NON-EMPTY STRING — a field the agent writing the
evidence block fills in itself. On the interactive path a human really was asked, so the string was
honest. On the autonomous path it cannot be: `engine.loop()` dispatches a headless
`claude -p --dangerously-skip-permissions` subprocess (`dv_harness/adapters/cli.py`) with the prompt
piped once through stdin and no live channel back to a human, so an in-flight AskUserQuestion is
unanswerable and the only way past the check was the LLM filling the field in — the gate passed
precisely when nobody had been asked. That is now closed:

- The gate re-derives the question_key from the DECLARED SCOPE and requires a persisted
  question-queue decision whose `current.source` is `question_queue.HUMAN_DECISION_SOURCE`
  (`dv_harness/waveform_dump_gate.py`). That is the same single sanctioned "a human really decided
  this" source `connectivity.enforce_bind_tier_policy()` / `apply_answered_questions()` already use
  for T3 binds — reused deliberately, so the harness cannot answer its own waveform escalation with
  its own earlier Tier-2 guess, and so there is one notion of "confirmed" in this codebase, not two.
  `confirmed_by` must additionally NAME that human (`current.decided_by`): a real decision cited
  with a false attribution is not a confirmation. A different scope is a different decision.
- The ask half is `dv-harness waveform-dump-scope ask --scope <scope> --level-or-depth <level>`,
  which files one canonically-keyed Tier-3 blocking question through the real `QuestionQueueStore`;
  a human answers it with the existing `dv-harness question-queue answer <Q-ID>`. There is no
  separate "waveform confirm" verb, because a second way to record a confirmation would be a second
  thing the gate has to trust. `dv-harness waveform-dump-scope status --scope <scope>` reports the
  same check (exit 2 when unconfirmed).
- **The engine files that question ITSELF on the autonomous path (2026-09-04, same-day gap
  close).** `ask_dump_scope_confirmation()` had exactly ONE caller in the repo — the human-typed
  `waveform-dump-scope ask` verb above. Nothing in `engine.py` called it, so a headless `claude -p`
  run that did not happen to shell out to that verb parked at WAIT_USER over an EMPTY queue:
  `question-queue list --blocking-only` showed nothing, `build_digest()` had nothing to report, and
  the human returning to the parked run had to read a Q-ID out of a `blocking_reason` string and
  hand-reconstruct the ask (scope AND level/depth) before `answer` had anything to answer. The loop
  opened and left behind no artifact capable of closing it — which made this section's own
  "parks at WAIT_USER with a real Q-ID" claim true only on the interactive path.
  `engine._file_waveform_dump_scope_question()` now runs at the exact point `run_stage()` assigns
  WAIT_USER, reading the scope and proposed level/depth off the SAME
  `focused_wave_debug_window_gate` evidence block the gate just rejected, and appends the real
  `question-queue answer <Q-ID> ...` command to the `blocking_reason`. It files a QUESTION and never
  a DECISION — only `answer_question()`, i.e. a human, writes one — so the human checkpoint is
  unchanged; what changed is that the human is handed an answerable Q-ID instead of an instruction
  to file one. It files nothing when the block declares no scope/level (that is agent error with its
  own remedy, not a missing human decision), nothing for a non-waveform NEEDS_USER_INPUT, and
  nothing when a question for that scope is already on file (`add_question()` appends rather than
  deduping, so re-filing would grow duplicates and re-arm `digest_batch_id` on a question a human is
  already sitting on). Every outcome is a real `WAVEFORM_DUMP_SCOPE_QUESTION_FILED` /
  `..._FILE_FAILED` event in `.dv-harness/events.jsonl`, and the filing is best-effort — a queue
  failure must never turn an already-correct WAIT_USER park into a crash.
- An unconfirmed dump scope now STOPS the autonomous loop instead of failing it. `gates.py` maps
  the gate's confirmation failures to the `NEEDS_USER_INPUT` verdict INTAKE already used, which
  `run_stage()` turns into `Status.WAIT_USER` and `loop()` returns on — so the question is not
  re-dispatched at a subprocess that cannot answer it until `max_stage_retries` is burned and the
  graph's FAIL edge is taken with the question still open. An UNRELATED failure of the same gate (a
  bad FSDB window, a missing evidence hash) stays an ordinary retry-worthy `GATE_FAIL`.
- Proven on the real path — the real gate subprocess, the real shipped graph, a real
  `QuestionQueueStore` on disk, and a real `loop()` that stops at WAIT_USER after exactly one
  dispatch and then gets through once a human answers — by
  `dv_harness_tests/test_waveform_dump_scope_human_confirmation.py`.

**Disclosed residual**, in the same spirit as `require_tier`'s and `require_qualified_conclusion`'s:
this closes the gate on the WAVEFORM decision specifically. The broader "a headless autonomous run
has no channel to ask a human anything mid-flight" limitation is unchanged — the fix is that such a
run now parks at WAIT_USER with a real Q-ID the ENGINE filed for a human to answer, not that the
subprocess gained a way to ask. The round-trip is still asynchronous and still requires a human to
come back to it: the run stops, and only `dv-harness question-queue answer` followed by a fresh
`dv-harness start --loop` resumes it.


## Simulation Observability Default

Normal simulation/regression defaults to FSDB OFF.
VIP trace/report may be enabled independently when supported by the current VIP/project.
Escalate to FSDB only when signal-level waveform evidence is needed.
FSDB enablement must pass the user-confirmed waveform scope/level gate.


## First-Failure Waveform Rerun

Initial simulation defaults to FSDB OFF.

If the simulation fails and signal-level evidence is required:
- rerun the failing testcase with targeted waveform enabled,
- confirm dump scope and level/depth,
- terminate at the first relevant failure/error/fatal/missing/mismatch,
- optionally retain only a minimal post-failure margin,
- do not run the full testcase unless later evidence is explicitly needed.

Regression-batch pipeline shape: push -> build -> verify -> run. The first pass runs the full batch
with FSDB OFF (per Simulation Observability Default). Only the subset of simulations that produced
a real UVM_ERROR or terminated abnormally (fatal/crash/timeout, not a clean UVM_FATAL-free PASS)
get selectively rerun with WAVE=1 (targeted waveform per First-Failure Waveform Rerun above) --
never blanket-rerun the whole batch with waveform on just because some tests failed.


## No Golden-Reference Content Mining

Forbidden methodology: "mine content from a completed reference environment -> have the generator
reproduce it -> verify it matches." This is not genuine generation, it is copying a finished answer
and relabeling the copy as if the harness had produced it from first principles. Even when a real,
locally-available reference environment exists (e.g. USB_UVM_Handoff) and even when the goal is
explicitly "100% parity" with it, protocol-behavior CONTENT — virtual sequence/pattern logic,
scoreboard checking logic, coverage bin/covergroup content, vPlan entries, command.txt scenario
content — must be derived from PRIMARY sources: VIP examples/user manual/source code/class
reference for branch-B/VIP-driven content, DUT RTL/PHY documents/programming guide for
branch-A/branch_fw-driven content (same sourcing already required by `vip-scenario-branch` and
`interrupt-event-dispatch` for any branch-B or branch-A/branch_fw modification — this rule makes
explicit that "modification" includes original content generation, not just edits to existing
files).

A completed reference environment may still be used AFTER independent generation, to measure and
report fidelity/gap (structural comparison, "how close did the independently-generated content
get") — that is legitimate verification, not generation. It must never be the source the generator
reads FROM to produce the content in the first place.


## Generated Content Language

Conversational replies to the user follow the user's own language preference (Traditional Chinese,
technical terms stay English). This is independent from generated deliverable content: all UVM
environment/testbench files, generator output, code comments, and any other artifact written into
the verification environment itself must be in English, regardless of what language the
conversation is conducted in.


## gh CLI + PR-Only Governance Policy (2026-09-03)

L5 governance requirement: an agent (Claude Code or any other automated
caller) may `git branch` / `git commit` / open a PR (`gh pr create`), but
must **never merge or push directly into a protected branch** (`main` or
`master`). Human review via PR is the only path onto those branches. This
is additive to, not a replacement for, the existing git-safety language in
`CORE/git-push-gate` (secret/scope/diff/commit-message discipline before
any push) and `CORE/git-workflow` (the full SYNC->...->PUSH lifecycle,
including its own "禁止自動 force push" rule) -- this section adds the
specific main/master-protection rule those two skills did not yet state.

**Real current state of this repo (re-checked 2026-09-04, kept honest
rather than assumed -- the 2026-09-03 wording below it was already stale
within a day, which is exactly why this paragraph is dated)**:
- A GitHub remote now EXISTS: `remote.origin.url =
  https://github.com/YuTienL/DV_Agent_Harness.git`, reachable
  (`git ls-remote origin` exits 0) but currently **empty** -- it returns no
  refs, and `master` has no upstream. So there is still no live PR workflow
  and, with no branches on the remote, no server-side branch-protection
  rule can exist on it yet. What HAS changed since 2026-09-03 is that a
  `git push origin master` from this repo is now a real, reachable
  operation rather than `fatal: No configured push destination.` -- i.e.
  the local hook gate below is now the thing that actually stands between
  an agent and a direct write to `master`.
- The local hooks below are **INSTALLED and live** (see enforcement item 2).
- `gh.exe` v2.99.0 is installed at `C:\Program Files\GitHub CLI\gh.exe` but
  is **not on PATH**, including in a fresh shell -- invoke it by full path
  until that is fixed. (An earlier build report claimed "a new terminal
  will see `gh` on PATH"; that claim was false and is corrected here.)

**Layered enforcement**:
1. **Primary (still ASPIRATIONAL here): server-side branch protection** on
   `main`/`master` requiring PR review before merge, disallowing direct
   pushes. This is the authoritative gate -- it holds even if a local hook
   is missing or bypassed. Not in force today: the `origin` repo is empty,
   so it has no branches to protect yet. Set this up as soon as the first
   branch is pushed; until then layer 2 is the only gate.
2. **Secondary (INSTALLED AND LIVE, verified 2026-09-04 --
   `git config --get core.hooksPath` returns `tools/git-hooks`; it was
   activated on 2026-09-03 *after* the original build task's own report was
   written, which is why that report and this section both used to say
   "NOT YET INSTALLED"): local
   `tools/git-hooks/pre-push` and
   `tools/git-hooks/pre-merge-commit`**, backed by
   `dv_harness/git_governance.py` (`dv-harness git-guard`). These detect an
   AI-agent execution environment using the same env-marker pattern
   `tools/remote/remote_relay.py`'s own Layer 2 guard already established
   (`AI_AGENT_ENV_MARKERS`, reused via import -- not duplicated) and BLOCK
   (non-zero exit, which git treats as hook failure) a direct push/merge
   into `main`/`master` from that environment. A human pushing/merging from
   their own interactive terminal (no agent marker present) is never
   blocked by this gate -- see `tools/git-hooks/README.md` for install
   (`git config core.hooksPath tools/git-hooks`; note git does NOT clone
   `core.hooksPath`, so every fresh clone must re-run that one line) and
   the deliberate fail-open behavior when Python is unavailable.
   This gate is proven end-to-end by `dv_harness_tests/test_git_hooks_e2e.py`,
   which drives a REAL `git push` and a REAL `git merge --no-ff` in a
   throwaway repo using these same hook scripts and asserts git itself
   aborts the operation, nothing lands on the remote, and a
   `GIT_GUARD_DECISION` reaches `dv-harness audit` -- so the claim in this
   section is a tested claim, not a description. Those tests also assert
   this repo's own `core.hooksPath` is still set, so the "INSTALLED AND
   LIVE" statement above cannot silently go stale again.
3. **Change-budget / blast-radius gate (2026-09-06, ADDITIVE — it never
   relaxes layers 1-2)**: `dv_harness/change_blast_radius.py`, run by the
   SAME `dv-harness git-guard` invocation as layer 2, but only on a
   push/merge layer 2 already ALLOWED — so it can turn an allow into a
   block and never a block into an allow. Layers 1-2 ask WHERE a change
   lands; this asks HOW FAR IT REACHES, from three measured (never
   self-declared) signals: files touched in the real diff (via
   `change_impact.changed_files()`), the transitive importer closure of the
   changed `dv_harness/*` modules from a real `ast` parse of the package's
   own imports, and whether the change edits a file that IS a gate (derived
   from `autonomy_levels.LEVEL_C_ENFORCEMENT`'s checked `cites` table, plus
   `tools/git-hooks/`). Over threshold (`WIDE`, or any `GOVERNANCE` file) an
   AGENT push is blocked until a human records a real approval under
   `dv-harness approve CHANGE_BLAST_RADIUS` whose note carries that
   assessment's `digest` — the pin is what stops it degrading into a
   permanent blanket bypass, since growing the change moves the digest and
   retires the approval. A human's own push is never gated on change size,
   same rule as layer 2. No real diff (no git, new branch with no
   merge-base) ⇒ `NOT_ASSESSABLE` and allowed: an environment problem must
   not masquerade as a policy finding. Inspect any range without pushing via
   `dv-harness blast-radius --base <rev> [--head <rev>]`. Decisions land as
   `BLAST_RADIUS_DECISION` in the same `.dv-harness/events.jsonl` trail.
   Proven by `dv_harness_tests/test_change_blast_radius.py`, which drives a
   REAL `git push` of a governance-file change in a throwaway repo, asserts
   git aborts it and nothing reaches the remote, then records the real
   approval and asserts the identical push now succeeds — and separately
   asserts a `CHANGE_BLAST_RADIUS` approval CANNOT unlock a protected-branch
   push, i.e. that this layer cannot be used to get around layer 2.

Every `git-guard` decision that touched a protected branch is logged as a
`GIT_GUARD_DECISION` event in `.dv-harness/events.jsonl` -- the same real
audit trail `dv-harness audit` already surfaces (see
`.claude/agents/audit-change-governance-agent.md`, the agent responsible
for reading this trail back and answering "what changed, by what/whom,
when, with what evidence, is it reversible" from real sources only).

`gh` (GitHub CLI) is the sanctioned tool for opening/inspecting PRs
(`gh pr create`, `gh pr view`, `gh pr checks`) once a remote exists. An
agent may run any read-only or PR-creating `gh`/`git` command freely; it
must never run `gh pr merge` (or an equivalent `git push`/`git merge`
straight onto `main`/`master`) itself -- that action is reserved for a
human, per this section's own rule and `git-guard`'s enforcement of it.


## Remote Control Mode
Claude Web/App may control this local Claude Code session through Remote Control.
Remote Control is transport only; Harness governance remains authoritative.
Never expose SSH private keys or credentials to Web/App or long-term memory.


## Environment Generation Mode

Before CREATE ENVIRONMENT, select:
- SUBSYSTEM_MODE: build a protocol/subsystem environment.
- SYSTEM_LEVEL_MODE: select/reuse completed subsystem environments and compose Full-SoC/System-Level environment.

If a required subsystem is missing in SYSTEM_LEVEL_MODE, build it through SUBSYSTEM_MODE then return to composition.

**Dispatched in code at the generation entry point (2026-09-04), not left to the agent.**
`environment_mode_router.resolve_environment_mode()` had computed this decision on every stage
since 2026-09-01, but its result landed only in `route_info["environment_mode_decision"]` — the
prompt and the ReAct record. Nothing branched on it: the one official CREATE ENVIRONMENT entry
point, `tools/generate_protocol_uvm_environment.py` (the script all ten
`.claude/skills/PROTOCOL_BUILDERS/*/SKILL.md` invoke), called `ProtocolEnvGenerator`
unconditionally, so a genuine two-subsystem request silently produced ONE subsystem environment
and `soc_environment_composer.compose_soc_environment()` fired only if an agent happened to know
to hand-assemble a `system_level_validator` evidence block for the SYSTEM_LEVEL stage instead.
That script now routes through `dv_harness/uvm_generator/create_environment.py`, which:
- resolves the mode with the real router and dispatches to `ProtocolEnvGenerator` (SUBSYSTEM_MODE)
  or `compose_soc_environment()` (SYSTEM_LEVEL_MODE) — a branch in FRONT of the existing path, so
  a single-protocol manifest still generates byte-identically;
- composes only from the REAL registry (`read_registered_subsystem_entries()`, written solely by
  `engine.py`'s `_persist_subsystem_registry_entry()` on a gate-validated SIGNOFF PASS), never
  from what the caller claims;
- REFUSES with `SubsystemModeRequiredError` naming the missing subsystems rather than composing
  the registered subset — the "build it through SUBSYSTEM_MODE then return to composition" rule
  above as enforced code, not trusted prose;
- raises `EnvironmentModeUnresolvedError` on a request that names nothing, honoring
  `environment_mode_policy.json`'s `mode_must_be_explicit_before_generation` instead of defaulting.

The SYSTEM_LEVEL stage half is now proven through the REAL entry point too: the composer's only
prior test called the private `_compose_soc_environment_files()` directly, so the chain gate
evidence → `gates.py` verdict → PASS branch → `compose_soc_environment` → blackboard → event log
had never been executed end to end. `dv_harness_tests/test_system_level_soc_composition_wiring.py`
drives a real `DVHarness.run_stage("SYSTEM_LEVEL")` through all 14 real
`STAGE_GATES["SYSTEM_LEVEL"]` scripts to a real PASS and asserts the real `SOC_ENVIRONMENT_COMPOSED`
event and real generated `soc_tb_top.sv` content, plus the negative case (an unregistered
subsystem fails the stage and composes nothing).

**Two limits, disclosed rather than implied closed.** (1) `cross_subsystem_scenarios()` /
`end_to_end_scoreboard()` / `system_coverage()` still raise `NotImplementedError` on purpose:
that is protocol-BEHAVIOR content, which "No Golden-Reference Content Mining" requires be sourced
from primary per-subsystem VIP/DUT evidence, and a registry entry carries only identity/
qualification metadata. Closing them needs a real cross-subsystem topology descriptor
(address/interrupt/DMA maps) that does not exist yet. (2) This harness repo's own
`subsystem_environment_registry.json` is still legitimately EMPTY and mechanism #14 has never
fired in its production history — it has no multi-subsystem project of its own. The mechanism is
proven to fire when a real project supplies real registered subsystems; it was not made to "have
fired" here by writing fabricated registry entries into this project's real audit trail.

**The SYSTEM_LEVEL verdict now stands on the REAL cross-subsystem analysis, not only on
agent-typed evidence (2026-09-05).** Two disconnected tracks had been built for Flow B and never
joined. Track A (`environment_mode_router` → `create_environment.py` →
`soc_environment_composer.compose_soc_environment()`) was engine-wired but composed blind: its only
import was `.generator`. Track B (the `SYS-1..40` family — `subsystem_discovery.py`,
`system_resource_inventory.py`, `system_readiness.py`, `system_topology_analysis.py`, ...) does the
real evidence-grounded work — shared-resource conflict detection, active-driver-ownership blocking,
address/clock-reset reconciliation — but was reachable ONLY from human-typed `dv-harness system-*`
CLI verbs. Most seriously, `grep -rln dv_harness tools/verification_flow/system_level_*.py` matched
NOTHING: every one of the gates that actually decides SYSTEM_LEVEL PASS/FAIL was a pure JSON-shape
check over the agent's own evidence text, so a composed system environment could pass every one of
them on hand-typed evidence with zero real cross-subsystem verification.

`system_resource_inventory.real_cross_subsystem_findings()` is the wire — it calls the existing
`analyze_selected_subsystem_resources()` front door (so SYS-1's refusal to analyze an unselected
set is not bypassed) and flattens the result for a verdict. Three real consumers now use it:
- `system_level_resource_contention_gate.py` FAILs `ACTIVE_DRIVER_CONFLICT_UNRESOLVED` when the
  real analysis stopped/held automatic integration, and `SHARED_RESOURCES_CONTRADICTED` when the
  plan declares no shared resources at all while the real analysis found
  SAME_PHYSICAL/SHARED_LOGICAL relationships — the hand-typed "all clear" case.
- `system_level_composition_gate.py` FAILs `ACTIVE_DRIVER_CONFLICT_UNRESOLVED` when the subsystems
  the composition NAMES carry an unresolved ownership conflict, whatever its per-subsystem
  `interface_compatibility`/`clock_reset_compatibility` "PASS" strings claim.
- `compose_soc_environment(entries, manifest, root)` consults the same analysis BEFORE composing
  and raises `CrossSubsystemIntegrationBlockedError` rather than emitting a `soc_tb_top.sv` that
  instantiates two subsystems whose ACTIVE agents both drive one SoC port; what the analysis said
  is recorded in `soc_composition_manifest.json`'s `cross_subsystem_analysis`.

DETECTION is what was wired; ARBITRATION is untouched. A DRIVER_CONFLICT still STOPS at BLOCKED
and still needs a human to decide which subsystem owns the interface — SYS-12's
`SYS12_PREFERRED_MODEL` is carried through as text for that human, and nothing added here picks a
winner, resolves a conflict, or crosses SYS-39/40's approval boundary. Where the real analysis
cannot run over real evidence (no registry, fewer than two subsystems, environments not on disk)
every consumer reports an explicit `TRACK_B_ANALYSIS_UNAVAILABLE`/`SKIPPED_ANALYSIS_UNAVAILABLE`
with its concrete reason and changes no verdict — never a silent "clear". Proven end to end by
`dv_harness_tests/test_system_level_track_b_gate_crosscheck.py`, which drives the REAL gate scripts
as subprocesses over REAL synthetic environments and asserts a hand-typed "all clear" block is
REJECTED when the real analysis over the same subsystems finds two ACTIVE AXI masters on one port.


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


## Methodology Consolidation Rule

A process/method/workflow used in a session is not "done" once it produces a result once.
It only counts as done once it has been consolidated into a permanent Harness asset so future
sessions get it automatically, without needing the user to re-explain it:

- A validated evidence-gathering/verification METHOD (e.g. how many agents, how to keep them
  blind, what counts as a real disagreement, how to resolve one) is consolidated into the
  relevant `.claude/skills/**/SKILL.md` file — with concrete mechanics and a worked real example,
  not a restated abstract mandate.
- A validated multi-phase ORCHESTRATION SHAPE (e.g. Parallel Evidence Gathering -> Consensus
  Synthesis -> Implement -> Re-verify) is consolidated into a reusable, parameterized script under
  `.claude/workflows/`, callable by name via the Workflow tool — not left as a one-off ad-hoc
  scratchpad script that only this conversation can re-run.
- A validated code-level capability (a new generator schema field, gate, check) is consolidated
  into the actual engine source under `dv_harness/`, with regression tests, exactly as already
  practiced this session — never left as a hand-edited one-off file outside the engine.
- After every consolidation: sync `.claude/` (skills + workflows) to the `industrial` and
  `PACKAGE` deliverable trees, same as any other engine change.

This rule itself is Human-Override-able like everything else, but by default applies with no
need for the user to ask for it every time.

This applies at every level, not only surface-level skills/workflows: an AI-architecture decision
(e.g. inference confidence scoring, memory-tier design, routing/dispatch semantics, iterative
reasoning-loop design) must land as real, wired, tested code inside `dv_harness/` — never stay as a
standalone module nothing in the real engine flow calls, and never stay as prose-only skill
guidance describing a desired mechanism an LLM subagent is merely trusted to enact each time. Per
[[dv_harness_poster_gap_reaudit_2026_08_29]] (verify this memory is still current before trusting
it), several past "done" claims at exactly this level (inference math, memory-tier stores, the
ReAct loop, route/skill resolution) turned out to be real-but-unwired or hardcoded/non-evidence-
driven — re-check wiring, not just existence, before declaring an AI-mechanism item complete.


## Engineering Discipline Rules (2026-08-29)

Cross-cutting rules that apply to every file modification, in addition to the domain-specific
mechanics already codified in `.claude/skills/CORE/*`:

- **Comment hygiene**: every file edit must also remove any comment/description in that file that
  is now outdated, redundant, or unrelated to the current content — never leave stale explanations
  behind as edits accumulate.
- **No overly abstract naming**: identifiers, files, signals, IDs must name the concrete real
  thing they represent (protocol/port/register/branch/purpose) — never a vague generic label a
  reader would have to guess the meaning of.
- **branch-B / VIP pattern changes**: query VIP examples, VIP user manual, VIP source code and
  class/API reference FIRST — already codified in `vip-scenario-branch` (do not invent VIP
  API/class/sequence by guessing).
- **branch-A / branch_fw changes**: query DUT RTL source, PHY documents and any programming
  guide/register documentation FIRST — already codified in `interrupt-event-dispatch`.
- **Event/control register hierarchy**: any RTL instance/signal hierarchy path for an event or
  control register must be verified against current RTL evidence, never assumed/reused from a
  stale path — already codified in `interrupt-event-dispatch` (`SOURCE_HIER` field).
- **Real FW pattern is interrupt-driven, not polling**: understand the trigger register/config,
  CPU WRITE task to arm it, then event-driven wait on the resulting interrupt — never periodic
  CPU READ-task polling as the primary detection mechanism — already codified in
  `interrupt-event-dispatch` ("CPU Task 層級實作模式").
- **Concurrent bus arbitration**: APB/AXI transactions that can execute concurrently across
  `block` / `branch_a0` / `branch_a1` / other `branch_a*` against a shared resource must have an
  explicit, RTL-evidence-based arbitration policy modeled — already codified in `branch-mapper`
  ("AMBA M×N Mapping"). Unrelated resources must stay independently parallel.
- **command.txt change-impact check**: every file/generator-schema modification must be checked
  against `.dv-workflow/command_inventory.csv` for which existing command.txt/scenario cases it
  could affect, and the affected set re-verified after the change — already codified in
  `command-inventory` ("Change-Impact Check").
- **Architecture-conformance audit**: every generated/modified environment and file must be
  checked against the current canonical naming architecture —
  `block + branch_a0/1/2/3... + branch_fw (supports parallel Port1/2/3...) + branch_b0/1/2/3...
  (VIPs)` — legacy/pre-v8 naming (non-underscore `branch_a{i}` forms, missing `branch_fw`,
  non-parallel-port assumptions) found during any review must be flagged and corrected, not
  silently left in place. Term semantics: `block` = SoC global initial tasks; `branch_a*` =
  DUT+PHY initial tasks, one parallel branch per DUT port; `branch_fw` = the FW service loop,
  one parallel branch per port; `branch_b*` = VIP-driven parallel tasks. Port numbering (whether
  a given DUT's ports start at 0 or at 1) must be verified against that DUT's actual RTL port
  numbering for the current project, never assumed from this doc's own `Port1/2/3` example
  text or copied from a prior project.
  `D:\DV\Task\DV_Agent_Harness_L5\USB_UVM_Handoff` is the canonical structural template for
  DV Agent Harness L5's VIP-based verification environment generation, at both SUBSYSTEM_MODE
  and SYSTEM_LEVEL_MODE — subject to the same "No Golden-Reference Content Mining" rule above:
  use it to check structural/organizational conformance, never as a source to mine
  protocol-behavior content from for a different project.
  **Consolidation status (audited 2026-09-02, see MEM-7F2DCD9E83/MEM-53FCE2C191/MEM-1669464837
  for full evidence):** file structure, verification-environment composition (env/agent/scoreboard
  wiring), and VIP-examples grounding are real, code-consolidated assets in
  `dv_harness/uvm_generator/*.py` (20+ line-cited references) and
  `dv_harness/uvm_generator/templates/sim_scripts/` (a real, now chip-configured copy of
  `USB_UVM_Handoff/sim/scripts/`), enforced against direct golden-reference citation by the real
  `protocol_isolation_gate`. The command.txt/pattern content architecture gap (`block`/
  `branch_a`/`branch_fw`/`branch_b` task composition, fork/join semantics, named
  arbitration/ordering traps) was closed 2026-09-03: distilled, generalized (USB kept only
  as clearly-labeled illustration, never as vocabulary) into a new
  `.claude/skills/CORE/pattern-architecture/SKILL.md` — the five-layer shape, the
  join-vs-join_any rule and why the "every branch guaranteed to run forever" justification
  expires, six recurring trap classes, and what varies vs. stays fixed by test intent
  (see `.work/gap-close-command-txt-report.md`). `command-generator/SKILL.md` now
  cross-references it (which command IDs must exist vs. how a pattern's internal task
  composition must be built) rather than duplicating it. The Makefile/sim-scripts migration gap
  (2026-09-02 audit: 5 files never carried over) was closed 2026-09-03: `analyze_sim.sh`,
  `apb_timing_report.sh`, `dpdm_report.sh`, `irq_report.sh` (the latter three sharing one
  `fsdb_signal_report.sh` engine, per-question wrappers only) and `check/gen_scaledown.py` are
  now genericized templates in `dv_harness/uvm_generator/templates/sim_scripts/` (see
  `.work/gap-close-makefile-report.md`). The consolidated part of this directory still goes
  unused unless an agent is explicitly told to survey
  `dv_harness/uvm_generator/templates/sim_scripts/` before hand-authoring build infrastructure —
  citing one sibling file in this directory (as this document previously did for
  `regression_list_manager.py`) is not sufficient for a dispatched agent to discover the rest.
- **Non-USB topology variants (2026-09-01, UNTESTED placeholder guidance)**: the canonical
  `block/branch_a*/branch_fw/branch_b*` naming above was reverse-distilled from, and has only
  ever been validated against, USB. Two topology-shape variants have since been added as
  clearly-labeled, explicitly UNTESTED generic guidance for a future non-USB pilot to start
  from — neither has been validated end-to-end and neither changes any protocol's
  genericity_status from untested/structurally-incompatible to working: (1) a **simplex
  streaming `branch_fw` variant** (RX-only/TX-only DUT, e.g. MIPI CSI-2/DSI-shaped) in
  `interrupt-event-dispatch/SKILL.md` — "Simplex Streaming branch_fw Variant" section; (2) an
  **AMBA-as-primary-DUT master/slave redefinition** of `branch_a*`/`branch_b*` (fabric IS the
  DUT, not an overlay on top of pre-existing ports) in `branch-mapper/SKILL.md` — "AMBA-as-
  Primary-DUT Master/Slave Redefinition" section. A future agent building a non-USB environment
  (CSI-2/DSI, or an AMBA-fabric-as-DUT/`SYSTEM_LEVEL_MODE` environment) should read these
  sections first rather than starting from zero.


## Agent-Authored Change Accountability (2026-09-03)

Explicit, written policy so this is settled before it becomes a real incident, per the user's
own reasoning: without this stated up front, no human feels safe clicking Approve on an
agent-authored change, and the harness stays permanently stuck below L5 regardless of how good
its technical output is.

- **The agent is a tool, not an accountable party.** Claude Code (or any automated caller)
  proposes; it never bears responsibility for a merged/pushed change's consequences.
- **The human approver of a PR/merge carries the same responsibility as if they had authored the
  change by hand.** Approving an agent-authored PR is not a lower-scrutiny action than approving
  a colleague's PR — the approver is the accountable party for any escape that change causes,
  exactly as with any other PR they approve.
- This is why `gh CLI + PR-Only Governance Policy` above exists as a hard technical gate (agent
  proposes via PR, never merges/pushes to `main`/`master` directly): the accountability model
  above only works if there really is always a human decision point in between an agent's
  proposal and a protected branch. Removing or bypassing that gate would also remove the
  precondition this accountability policy depends on.
- This policy does not change any existing evidence/verification requirement in this file (the
  Evidence Truth Rule, stage-gate checklists, etc.) — those still apply in full before a change
  reaches PR stage. It only settles the separate question of who is accountable once a human
  clicks Approve.


## Trust Progression for Autonomous/Semi-Autonomous Work (2026-09-03)

Real-world adoption should climb by task risk, not jump straight to the riskiest category:

1. **Start with near-zero-risk tasks**: log/failure triage, report generation, coverage
   summarization. A wrong output here costs a few minutes of a human's attention, not a bad
   tapeout decision.
2. **Only after a track record accumulates on tier 1** (accuracy data the team has actually
   looked at, not an assumption) should autonomy extend toward stimulus/pattern modification —
   the tier where a wrong output can silently produce a false PASS.
3. This is a recommended adoption ordering for the humans operating this harness, not a
   mechanically enforced gate in the engine — record it here so it is a deliberate team decision
   each time scope expands, not a default that happens by not thinking about it.

**Deliberately preserved knowledge asymmetry**: as this harness gets better at autonomous
debug, new engineers get fewer chances to debug a real failure by hand — which is a genuine
long-term cost to the team's own capability, not merely a short-term efficiency tradeoff. Teams
adopting this harness should deliberately route some fraction of real failures to a human for
hands-on debug rather than letting the harness resolve every one it technically could, treating
this as an investment in the team's future capability rather than lost efficiency today.


## Bind-Location Rules (2026-09-03)

Five hard project rules for every `bind` statement an agent proposes or reviews — not
suggestions, and not judgment calls left to per-instance discretion. Backed by real code in
`dv_harness/connectivity.py` (the 4-tier bind-confidence classifier, existing-bind grep, and the
3-gate connectivity pipeline — see `.work/mcp-bind-connectivity-report.md`),
`dv_harness/phy_boundary.py` (the mount-layer decision, Rule 5) and
`dv_harness/uvm_generator/bind_mechanism_generator.py` (evidence-gated `bind`/hook-skeleton
emission, already real — this section adds the location rules that generator's own output
must satisfy; it does not re-implement that generator's emission logic here).

1. **Bare module name vs. full instance path.** Binding to a bare module name applies to
   **every** instance of that module. Appropriate at IP-level (one DUT instance, one intended
   bind target). Usually **wrong** at SoC level — a bare-module-name bind against a module
   instantiated more than once silently binds all of them. SoC-level work must always bind by
   full instance path (`chip.core.subsys0.usb0`, not `usb3_subsystem`).
2. **Centralized `*_bind.sv` files under `tb/`.** Every bind statement lives in a centralized
   `*_bind.sv` file under `tb/` (matches the existing `<ip>_uvm_bind_inst.sv` — "every bind, in
   ONE file" — convention already documented in `ip-uvm-dv-gen/SKILL.md`'s directory table). RTL
   files are **read-only**: an agent must never insert a `bind` statement directly into RTL.
3. **Clock/reset through the bind's own port list.** Clock and reset must be passed explicitly
   through the bind instance's own port connections, never grabbed via a cross-level
   hierarchical reference (`chip.core.clk` reached through an XMR from inside the bound module).
   A hierarchical grab breaks at gate-level netlists and after any wrapper swap — the bind's own
   port list is the only connection method that survives both.
4. **No generate/for-loop bind targets.** Any bind-target path containing a generate-block or
   for-loop construct must be expanded to explicit literal indices in the actual bind statement
   (`chip.core.phy_array[0].u_phy`, `chip.core.phy_array[1].u_phy`, ... — never
   `chip.core.phy_array[*].u_phy` or an unrolled-loop placeholder). No wildcard/loop-based bind
   target is accepted, precisely because a generate-loop bind path is one of the two situations
   `connectivity.py`'s T3 tier explicitly flags as most error-prone (the other being inconsistent
   wrapper depth across a hierarchy).
5. **The PHY model decides the mount LAYER first; only then is the hierarchy path a question.**
   Rules 1–4 all assume the layer is already settled and ask *where inside it* to bind. Rule 5 is
   the step before them, and it is an ORDERING rule: decide from the PHY model's existence and
   type which layer a monitor may mount at, and only after that layer is fixed go looking for the
   instance path. Choosing a target path first — typically by recognising a familiar module or
   signal name in the RTL — and asking afterwards whether a PHY sits in between is the backwards
   order, and it is not a harmless reordering. It is how a bind lands on line-rate serial lanes: a
   protocol VIP monitor there decodes nothing without a PHY model, so it **elaborates (Gate 1
   PASS), sees a toggling clock and a released reset (Gate 2 PASS), and only fails at Gate 3, as a
   silent monitor** — the most expensive place in the pipeline to discover a mount-layer mistake.
   Note the tier classifier cannot catch this: a serial-lane bind target can be a perfectly clean
   T1 structural match, because layer-correctness and path-correctness are independent properties.
   That is why this is a separate gate rather than another tier.
   The confirmed real drift this rule is written from (2026-08-31, recorded in
   `.claude/agents/IP_UVM_DV_Gen.md:541-649`): an agent disabled a whole PHY instance for USB3 on
   the assumption that PIPE4 replaced it, and was corrected by the user — 「USB3 也是要經過 PHY，
   不是 PIPE 介面」. The agent had reasoned from interface naming instead of from whether a PHY
   model was actually in the path.
   **Enforced in code (2026-09-04), not by review**: `dv_harness/phy_boundary.py` derives the
   serial/parallel boundary from the same verible-parsed port table `env_manifest.py` produces,
   and `bind_mechanism_generator.assert_phy_boundary_decided_first()` runs that decision as a gate
   **before** the tier gate inside `validate_bind_entries()`/`emit_bind_sv()` — a SERIAL-only or
   UNDECIDABLE boundary raises `PhyBoundaryValidationError` and nothing is written. An entry may
   declare the boundary signals it connects through as `phy_boundary_signals`, which additionally
   refuses binding the serial lanes of a MIXED boundary (a boundary whose document says
   `bindable: true`, so the layer check alone would pass it). `tools/generate_bind_mechanism.py`
   takes `--phy-boundary <phy_boundary.json>` and `--require-phy-boundary`.
   **Disclosed residual**, mirroring `require_tier`'s: `require_phy_boundary` defaults to False, so
   a caller that supplies no boundary document at all still emits. That default is deliberate — an
   IP-level DUT with no PHY sub-block genuinely has no boundary to decide — and it means Rule 5 is
   hard-enforced whenever a boundary is in scope and known, not universally. Pass
   `--require-phy-boundary` for the strict contract.

Rules 1–4 (the path rules) are enforced by review, not (yet) by a standalone lint gate — Rule 5
is the exception and hard-blocks in code, per its own paragraph above. `connectivity.py`'s
T1–T4 tier classifier and its `grep_existing_binds()`/matrix output make a violation visible (a
bare-module-name target at SoC scope, or a generate-index-bearing bind target, shows up directly
in the connectivity matrix's `bind_target` column for a human reviewer to catch), but does not
yet hard-block generation on one. See the report referenced above for what is real/tested today
versus NOT_AVAILABLE-by-honest-design (anything requiring a live `simv`, a licensed VCS install,
or `slang`, none of which are present in this environment as of this writing).

**The bind-CONFIDENCE tier, like Rule 5 but unlike path rules 1–4, DOES hard-block generation
(2026-09-04).** It is the second of the two independent gates `validate_bind_entries()` runs, and
runs after Rule 5's: layer first, then path confidence. `connectivity.assert_t3_never_auto_accepted()` previously had no caller anywhere
in the repo — its own docstring named a "downstream consumer" that did not exist — so the real
emission path (`tools/generate_bind_mechanism.py` → `uvm_generator.bind_mechanism_generator.
emit_bind_sv()`) would write a naming-heuristic-only bind into a `.sv` file with no tier check at
all. `validate_bind_entries()` now calls `connectivity.enforce_bind_tier_policy()` before emitting
anything, which refuses, as a hard `BindTierError` and before any file is written:
- **T4** (`T4_BIND_MUST_GO_TO_QUESTION_QUEUE`) — never emittable; it belongs in the question queue
  via `build_t4_question_queue_entry()`, not in a bind file.
- **T3 without a real human confirmation** (`T3_BIND_REQUIRES_HUMAN_CONFIRMATION`) — the entry must
  carry `human_confirmation: {source, confirmed_by, basis}` whose `source` is
  `question_queue.HUMAN_DECISION_SOURCE`. That is the same single sanctioned decision source the
  question queue already uses to stop the harness answering its own Tier-3 escalation with its own
  earlier guess — deliberately reused, not a second parallel notion of "confirmed".
- an unrecognized tier string, and (under `--require-tier` / `require_tier=True`) an entry carrying
  no tier at all.

**Disclosed residual**: `require_tier` defaults to False, so an entry carrying NO tier is still
emittable. This keeps the existing 3-field entry contract (`target_instance`/`ports`/`reason`,
documented in every PROTOCOL_BUILDERS skill and used by the real
`examples/generated_usb_real_evidence_v1/manifest_inputs/usb_bind_topology.json`, re-verified
working) unbroken. What is closed hard is the dangerous case: an entry the pipeline already
classified as unconfirmed or undecidable being emitted anyway. Pass `--require-tier` for the
strict contract.

Two matrix-level guarantees were wired at the same time, both previously uncalled primitives:
`write_connectivity_manifest()` now runs `verify_matrix_self_check_identity()` (Part C's
sum(verified interfaces) == sum(VIP instances) + sum(exemptions), with both terms read off the
real matrix rather than caller-supplied) and `assert_role_provenance()` BEFORE writing, so a
manifest on disk is one that reconciled — an uncovered no-VIP interface or a hand-typed
naming-derived `role` raises instead of producing an authoritative-looking artifact.
`ConnectivityRow.from_dut_port()` is the sanctioned row constructor that derives `role` through
`determine_role_from_port_direction()` instead of accepting a typed-in string.

**The 3 machine gates are a REQUIRED workflow checkpoint, not merely available tooling
(2026-09-03, Gap #2 closure).** `connectivity.py`'s 3-gate standard (elaboration / static
zero-time connectivity / transaction activity) existing and being importable is not sufficient —
it must actually be RUN. This was confirmed as a real gap: the live `usb31_dev_uvm` build reached
first successful compile and moved on through later build steps without the 3-gate standard ever
being applied to it, because the standard was built mid-session by a separate concurrent effort
and nothing retroactively flagged that in-flight build against new verification infrastructure.
Concretely, for every IP_UVM_DV_Gen build from this point forward (full mechanics in
`.claude/agents/IP_UVM_DV_Gen.md`'s "Mandatory bind-verification checkpoint" subsection under Step
9):
- Running Gate 1 (`run_gate1_elaboration_check()`) and Gate 2 (`evaluate_zero_time_connectivity()`
  / `run_gate2_against_live_simv()`) is REQUIRED immediately after the first successful
  compile/elaboration — an honest NOT_AVAILABLE result (no `slang`/`vcs`/trace present) satisfies
  this checkpoint; never invoking either gate at all does not.
- Gate 3 (transaction activity) cannot PASS or FAIL until a real pattern actually completes. That
  is expected and must be tracked explicitly as **PENDING**
  (`evaluate_transaction_activity_status(pattern_completed=False)`) — `connectivity.py`'s
  `GateStatus` enum now carries `NOT_YET_RUN` and `PENDING` alongside `PASS`/`FAIL`/
  `NOT_AVAILABLE` specifically so this state is never conflated with FAILED, with "not
  applicable", or silently omitted from a report.
- Every build-status report produced from that checkpoint onward must explicitly carry Gate
  1/2/3's current status (`render_bind_verification_status_markdown()` /
  `bind_verification_status_block()`) — a report that omits this section is a defect in the
  report. `python -m dv_harness.uvm_generator.bind_verification_lint <report_path>` is a real,
  standalone check that flags exactly this against any build tree's own status-report artifact
  (markdown or JSON), independent of which agent or code path produced it.
- `assert_bind_gates_checkpoint(first_compile_succeeded, gate_report)` is the corresponding
  code-level assertion (raises `BindGateCheckpointError`, never a silently-ignorable bool) for any
  future code path that comes to drive this build mechanically instead of via agent-followed
  prose. See `.work/gap-close-mandatory-gates-report.md` for the full evidence and verification.

**The gates are also a STANDING recipe re-run on every RTL update (2026-09-04).** The checkpoint
above fires once, at first successful compile. `connectivity.py`'s own
`run_gate3_against_live_simv()` docstring additionally called for the gates as "a standing
`just connectivity-check` recipe re-run on every RTL update" — a recipe that did not exist
anywhere (no justfile target, no CI job, no hook; `connectivity.py` was imported by nothing but
itself and `bind_verification_lint.py`). It now does:
- `just connectivity-check` runs all 3 gates through `connectivity.run_machine_gates()` (never a
  subset) via the real `dv_harness/connectivity_check.py` runner, and records the resulting
  statuses **together with a content fingerprint of the RTL they were produced against**
  (`.dv-harness/connectivity_check_state.json`, plus a lint-clean
  `.dv-harness/connectivity_check_report.md` rendered by the same
  `render_bind_verification_status_markdown()`).
- `just connectivity-check-status` (= `python -m dv_harness.connectivity_check --check-only`) is
  the automatic TRIGGER: it runs no gate, only re-computes that fingerprint and exits **2** when
  the RTL moved since the last real gate run, or when no run was ever recorded. Wired as a CI
  step in `.github/workflows/dv-harness-ci.yml`, so "RTL changed but nobody re-ran connectivity"
  becomes a real failure instead of something a reviewer has to notice. Content-hash based, not
  mtime — a no-op touch does not fire it, and a content change that preserves mtime does.
- Inputs are declared once per project in `.dv-harness/connectivity_check.json` (`rtl_sources`
  globs, `filelists`, `top_module`, optional `signal_trace_path`, monitor transaction counts,
  `pattern_completed`). A project without that file reports NOT_CONFIGURED rather than a silent
  pass; a config whose `rtl_sources` match zero files is a hard config error, never a vacuous
  constant fingerprint that would compare equal forever. **This harness repo itself has no RTL
  tree, so its own CI step is honestly a no-op today** — the mechanism is real and tested
  (`dv_harness_tests/test_connectivity_check.py`), the RTL it watches is per-project.


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

## Context Budget: 3 Tiers + MCP-First Routing (2026-09-03)

An agent's context window is a finite verification resource and is budgeted like one. The tiers
below are not advice — tier 1 is a real `PreToolUse` deny and tier 2 is a real `SessionStart`
injection. Policy lives as data in `dv_harness/context_budget.policy.json` (validated against
`dv_harness/schemas/context_budget.schema.json`); logic lives in `dv_harness/context_budget.py`;
enforcement is `.claude/hooks/context-budget-guard.ps1` (registered for
`Read|Grep|Bash|PowerShell|NotebookRead`) and `.claude/hooks/context-resident-pack.ps1`. Extend the
policy JSON for a project's own DUT/VIP roots — never the Python.

**Tier 1 — NEVER into context** (denied; four content classes, `NEVER-*` rule ids):
VIP source full text, raw PDF originals (user guides/protocol specs/programming guides),
whole-chip design·waveform·evidence databases (`.fsdb`/`.vpd`/`.vcd`/`simv.daidir`/the evidence
SQLite store), and complete simulation/regression logs. Every denial names its route forward — a
fixed MCP verb and/or the distiller that turns that content class into a bounded artifact
(`vip_user_guide_distill.py` for PDFs — corrected 2026-09-04 from `doc_extraction.py`, which only
LISTS `.pdf` in a suffix set and contains no PDF text extraction at all, so that route named a
script that could not perform it; `fsdb_report.py` for waveforms, `sim_log_analysis.py` for logs).
There is deliberately **no** distiller cited for VIP source: none exists — `vip_distill.py` is named
suggestively but normalises sim-log/job/fsdb evidence envelopes and never reads VIP source, so that
rule routes to `get_vip_config` and says so rather than sending you after a script nobody wrote.
Deliberate
carve-outs: VIP `Examples/` reference testbenches and `.f` filelists stay readable, because
denying the sanctioned reference material is the false positive that gets a gate switched off.

**Tier 2 — ALWAYS resident**: `CLAUDE.md` (this file — resident because the agent harness
auto-loads it), plus `.dv-harness/env.manifest.json`, `.dv-harness/run_profile.json`,
`.dv-workflow/hierarchy.json`, `.dv-workflow/phy_boundary.json`, injected as a size-capped summary
pack (`MAX_PACK_BYTES`, JSON summarised by shape, never inlined). Run
`python -m dv_harness.context_budget resident` to see current residency; it exits 2 while any
declared artifact is MISSING and prints the real command that would produce it. Residency in this
repo is still only `CLAUDE.md` (this harness has no RTL tree or VIP of its own to extract from),
but the extractor situation changed on 2026-09-04: **`phy_boundary.json` now HAS a real extractor**,
`dv_harness/phy_boundary.py`, which derives the PHY↔controller serial/parallel boundary from the
same verible-parsed port table `env_manifest.py` already produces and turns it into an explicit
bind-location decision (a SERIAL-only boundary is reported NOT bindable, because a protocol monitor
bound there passes Gates 1–2 and fails Gate 3 as a silent monitor). `hierarchy.json` is unchanged:
it still has a declared producer (`.claude/skills/CORE/hierarchy-discovery/SKILL.md`) but no
non-agent extractor. That is reported, not hidden.

**Tier 3 — LOAD ON DEMAND**: single-register/regmap lookups via `get_register` (never a whole
system regmap), the distilled per-protocol `docs/vip_ref/<protocol>.md`, and `docs/intent.md`.
Read one when a specific question needs it; never preload. As of 2026-09-04 both of those
distilled artifacts have real generators: `dv_harness/vip_symbol_index.py` indexes a VIP source
tree to declarations and `file:line` locations ONLY — never method bodies, which is what makes it
legitimate against tier 1's own `NEVER-VIP-SOURCE` denial — and renders `vip_ref/<protocol>.md`
from that index; `dv_harness/design_intent.py` renders `intent.md` and `constraints.md` from
schema-validated structured sources in which every legal-drop/backpressure condition REQUIRES a
document+section citation, so an uncited (i.e. possibly invented) condition cannot validate. The
matching `sys_regmap.json` / `init_seq.yaml` pair (`dv_harness/sys_regmap.py`,
`dv_harness/init_seq.py`) supplies the Gate-2 mode-bit precondition connectivity.py never had, so
a dead clock caused by an unwritten clock-enable reads as `PRECONDITION_NOT_MET` rather than as a
connectivity failure against a bind that was correct all along. See
`.work/gap-close-asset-table-asset-processing-table-14-rows-hierarchy-report.md`.

**MCP-first routing.** `dv_harness/mcp` exposes exactly 5 fixed, read-only verbs —
`get_vip_config`, `get_dut_port`, `get_register`, `get_topology`, `query_regression` — dispatched
through one `dispatch()` with no free-text fallback and no caller-supplied SQL. Anything those
verbs answer must be asked of them rather than read raw. Three honest limits, all covered by named
tests: the guard classifies literal paths only, so a shell-variable-indirected read
(`sed -n "1,50p" $M`) or a directory-indirected one (`ls <dir> | xargs cat`) still gets through;
`ls`/`find`/`stat`/`wc`/`file` may name a tier-1 file without reading it; and the guard fails open
if Python is unavailable. It is a large reduction in bypass surface, not a seal. A genuinely necessary tier-1 read gets a reasoned entry in the policy's `exemptions` array
(the rule still fires and is recorded in the decision) — never a silent retry.


## MCP Query Interface: the 5 Verbs (index) (2026-09-04)

The section above says routing goes through MCP first. This is the index that makes that
actionable: which verb answers which question, and which two files on disk this server is allowed
to touch. It is an index, not a manual — every verb's real parameter/result schema lives in
`dv_harness/mcp/schema.py` and the design writeup in `.work/mcp-server-report.md`; read those on
demand, never preemptively.

**The rule.** If one of these 5 verbs can answer your question, ask it — do not read the underlying
file. There are exactly 5, dispatched through one `dispatch()` with no free-text fallback, no
caller-supplied SQL, and no write verb of any kind; asking for a 6th name raises rather than
falling through to something general.

| verb | ask it when | required args |
|---|---|---|
| `get_vip_config` | you need a VIP instance's already-resolved config value (from a real zero-time elaboration dump, never a document) | *(none — omit both filters to list every captured instance)* |
| `get_dut_port` | you need one RTL module's ports or parameters, verible-parsed, with the source sha256 | `module_name` |
| `get_register` | you need one register's fields/offset/absolute address — never a whole regmap | *(none — omit all filters to list every register)* |
| `get_topology` | you need the UVM component hierarchy or the raw config_db SET/GET trace under some path | *(none)* |
| `query_regression` | you need regression evidence, via one of a fixed set of shapes — never raw SQL | `query_shape`, one of `latest` / `by_pattern` / `by_verdict` / `by_date_range` |

**Read-only fact sources.** This server reads exactly two things and writes neither. The manifest is
opened with `Path.read_text()` and the package has no writer; the evidence DB is opened
`read_only=True`, which DuckDB itself enforces at the engine level:

- `.dv-harness/env.manifest.json` — the 3-layer generated fact file (`vip_config` / `dut_facts` /
  `env_topology`), written only by `dv_harness/env_manifest.py`. Backs the first four verbs.
- `.dv-harness/evidence/evidence.duckdb` — the regression evidence store. Backs `query_regression`.

**Which protocols exist is deliberately not listed here.** Which protocols/VIPs an environment
actually contains is a manifest fact that changes per environment, not a rule that belongs in this
file — call `get_vip_config` with no arguments and read the `vip_type` of each captured instance. A
hardcoded protocol list here would be stale the day a second environment is built.

Run it against a real environment:

```
python -m dv_harness.mcp.server --manifest .dv-harness/env.manifest.json --evidence-db .dv-harness/evidence/evidence.duckdb
```

This section is **parsed and checked against the code on every test run**
(`dv_harness/mcp/claude_md_index.py`, `python -m dv_harness.mcp.claude_md_index`): the verb rows
must equal `verbs.VERBS`, each row's required args must equal that verb's real
`PARAM_SCHEMAS[...]["required"]`, the shapes must equal `regression_queries.QUERY_SHAPES`, the two
paths must equal the code-owned ones, and the invocation's flags must be flags `server.py` really
defines. Adding a verb without indexing it here fails a test. Moving the index into code without
holding the prose to it would only have created a second place to be wrong.


## Source Authority Order: 9 Levels, Enforced (2026-09-04)

When two sources disagree about the same fact, which one is true is decided by a fixed 9-level
order, highest first — not by which one an agent happened to read last, and not by judgment:

1. elaboration / actual simulation result
2. the reference Makefile/command.txt itself
3. DUT RTL
4. register file (DUT then Global)
5. existing testbench binds
6. controller doc/programming guide
7. IP user guide
8. VIP example
9. VIP document

This lived only as a paragraph in `docs/RUN_PROFILE.md` until 2026-09-04 — a repo-wide grep for
its own distinctive terms found zero hits outside that one paragraph, so it was a convention an
agent was trusted to have read, the exact failure class the Engineering Discipline Rules name. It
is now real code: `dv_harness/source_authority.py` (`AUTHORITY_ORDER`, `authority_rank()`,
`resolve_conflict()`) and `dv-harness authority order|check-doc|resolve`. The markdown paragraph is
PARSED and compared against the code on every test run (`assert_doc_matches_code()`), so the two
cannot drift apart in either direction — moving a rule into code is only an improvement if the
prose it came from is then held to it. The "(DUT then Global)" clause tier 4 carries is a real
sub-ordering (`REGISTER_FILE_SUBORDER`), not a parenthetical.

**It is not `tools/verification_flow/evidence_source_priority_gate.py`'s `ORDER`.** Both lists are
9 items long, which has already caused one mis-identification. That one is a DISCOVERY order (which
source to consult first for a fact you do not have yet, ending at `ASK_USER`); this one is a
CONFLICT order (which source wins when two you already read disagree). Separate mechanisms, kept
separate on purpose.

**A mismatch is escalated, not just reported.** `resolve_conflict()` deciding which VALUE to use
never means the losing artifact is fine to leave wrong, and two claims at the SAME tier cannot be
decided by the order at all. Both cases go to the real question queue through
`source_authority.escalate_conflict()`, which files a Tier-3 (`affects_spec_intent`) entry whose
two options ARE the two sides and whose per-option `rationale` is that side's evidence path.
`assert_both_evidence_paths_present()` runs BEFORE the record is persisted, so a conflict question
that names a disagreement without citing where both halves of it live can never reach the queue.

Two real detectors are wired into it. Both previously terminated at report text — the detectors
were real, the queue was real, the wire between them did not exist:
- `reference_pattern_audit.audit_directory(..., question_store=)`, i.e. `dv-harness
  reference-audit --escalate` — a host/DUT register-write asymmetry. Both halves come from the
  same tier-2 source (the reference pattern file), so the order returns
  UNDECIDABLE_SAME_AUTHORITY and escalating is mandatory rather than advisory. The missing side is
  cited AS an absence ("no DUT-side write to base BB00 offset 0020 in this file"), which is what
  makes an absence checkable by the person who receives it.
- `uvm_generator/address_map_verifier.verify_address_map(..., question_store=)` — a register
  document whose base address disagrees with the decoder. **This does not make committal
  blocking.** The decoder (tier 3) still wins over the doc (tier 6) mechanically, and the verified
  entry plus its `` `define `` are byte-identical with or without the store. What was missing is
  the OTHER question — which of the two artifacts is stale — which nothing asked anybody, and
  which a `//` comment inside generated Verilog is not an escalation of.

Both escalations are idempotent: the Q-ID is derived from the finding, so re-running a detector
over unchanged sources re-mints the same id instead of growing the queue. Proven end to end
against a real `QuestionQueueStore` (never a mock) by `dv_harness_tests/test_source_authority.py`.


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


## Harness-to-Remote-Agent-Path Deployment: `dv-harness harness-deploy` (2026-09-05)

`USAGE_MULTI_USER_SAFETY.md:16-19` records as 固化 standing policy that "every
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
clobber everyone else's, which is `USAGE_MULTI_USER_SAFETY.md`'s own "never share
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


## Loop Telemetry Events + the GUI Loop Engineering Center (2026-09-05)

LOOP_ENGINEERING section 108 names nineteen loop telemetry event types
(`LOOP_CREATED`, `LOOP_STARTED`, `LOOP_ITERATION_STARTED`,
`LOOP_ACTION_SELECTED`, `LOOP_VERIFY_COMPLETED`, `LOOP_PROGRESS_UPDATED`,
`LOOP_CONVERGING`, `LOOP_PLATEAU_DETECTED`, `LOOP_OSCILLATION_DETECTED`,
`LOOP_NO_PROGRESS`, `LOOP_RETRY_SCHEDULED`, `LOOP_BUDGET_WARNING`,
`LOOP_BUDGET_EXHAUSTED`, `LOOP_BLOCKED`, `LOOP_HUMAN_GATE_REQUIRED`,
`LOOP_RESUMED`, `LOOP_SUCCESS`, `LOOP_FAILED`, `LOOP_STOPPED`), and section 107
requires a GUI Loop Engineering Center -- a `Loop | State | Iteration | Verified
Gain | Budget | Plateau | Oscillation | Next Action` table with a fourteen-field
drill-down -- because "GUI must expose why a loop is running". A repo-wide grep
for each of the nineteen names on 2026-09-05 returned **0 hits for all
nineteen**; LOOP-1's own disclosed residual said so in as many words ("the other
nineteen names have no producer"). `dashboard.py`'s only `loop` hits were the
pre-existing single-run/continuous-run Start toggle -- a CONTROL, not
observability.

`dv_harness/loop_telemetry.py` is the vocabulary and the reader;
`engine.DVHarness.loop()` is the producer; `GET /api/loops` plus the Loop
Engineering Center card is the surface.

**Same event file, same writer, no second audit trail.** Every event goes
through `storage.StateStore.event()` into the one `.dv-harness/events.jsonl`
`_record_debug_loop_round()`, `_record_loop_state_observation()`,
`_spend_retry_exhaustion_budget()` and `dv-harness audit` already use.
`emit()` REFUSES a name outside section 108's nineteen: an unrecognized name
would be dropped silently by the reader while the emitter looked like it had
reported something.

**Every event is emitted at a transition `loop()` really makes**, and each is
one line from the decision it records -- LOOP_ITERATION_STARTED at the top of
the `while True` body, LOOP_ACTION_SELECTED before `run_stage()` carrying the
graph node's own `route`/`skills`, LOOP_VERIFY_COMPLETED after it carrying
`gates.effective_stage_gates()`'s real gate ids (section 87's verifier
separation, recorded rather than assumed), LOOP_RETRY_SCHEDULED at the one
`ss["status"] = RETRY` branch, LOOP_BUDGET_EXHAUSTED beside LOOP-3's ledger
spend. **Exactly one terminal event per loop session**
(`TERMINAL_LOOP_EVENTS`: SUCCESS / FAILED / BLOCKED / STOPPED) on every one of
`loop()`'s return paths -- two would be two contradictory answers to "how did
this end", and a test drives all of them (real takeover, real pause, a real
LOOP-3 circuit-breaker trip, real retry exhaustion, a real run-out-of-graph
close).

**Nothing is derived twice.** The state is `loop_contract.derive_loop_state()`'s
(`LOOP_STATE_TO_EVENT` is the one bridge, held total by
`assert_loop_state_mapping_total()`, and the four states that name no
section-108 event carry a real reason rather than a silent `None`); the budget
numbers are `policy.max_stage_retries` and LOOP-3's ledger payload; the
plateau/oscillation verdict is `loop_convergence.classify_loop_convergence()`'s;
the Next Action column is the REAL `inference.next_best_action()` through its
`gap_action_catalog` parameter, the domain-neutral engine section 10 forbids
re-implementing. `dashboard._overall_progress()` now DELEGATES to
`loop_telemetry.gate_verified_stage_count()`, so the progress bar and the
Verified Gain column cannot disagree about which stages count.

**LOOP-2's classifier is now engine-fired, which is what gives PLATEAU a
producer.** `loop_convergence` was REACHED but never run by the engine, so every
`LOOP_STATE_OBSERVED` carried `PLATEAU_NOT_EVALUATED` forever.
`engine._classify_loop_convergence_for_telemetry()` runs it at the one
low-frequency point where "is this a plateau, an oscillation, or just a hard
stage" is genuinely being asked -- the retry-exhaustion branch, once per
exhaustion, never per iteration -- and passes the report into the existing
`observe_verification_closure_loop(convergence=...)` parameter LOOP-2 already
built for it. The evidence database is opened READ-ONLY or not at all.

**Two progress metrics, never conflated.** `gate_verified_stages` is
per-iteration and is this engine's only per-iteration machine-verified signal
(an iteration that ran a stage and moved it by zero is LOOP_NO_PROGRESS --
section 110's LOOP-AT-26, artifact churn without verified gain);
`coverage_percent` is the cross-run series plateau is measured on. Every event
carries `metric`, so one can never be read as a statement about the other. An
UNKNOWN convergence verdict emits NOTHING: the classifier ran and could not
conclude, and recording that as a finding is the unearned claim
`PLATEAU_NOT_EVALUATED` exists to prevent. A `REGRESSION` verdict is reported as
LOOP_NO_PROGRESS -- the nearest true statement, since section 108 names no
regression event -- with the real verdict on the payload.

**Honest empty state, never a fabricated row.** A project whose loops have never
emitted an event reports `available: false` naming the `events.jsonl` it read
and the real `dv-harness start --loop "<goal>"` that would populate it. A
one-shot `dv-harness run-stage` and a `--dry-run` loop open no session at all
and emit nothing, because neither iterates.

**No human-approval gate moved, and observing authorizes nothing.**
LOOP_HUMAN_GATE_REQUIRED records that a human decision is OWED; it is not, and
cannot become, the decision. `loop_telemetry.py` does not reference
`ControlPlane`, `can_signoff`, `assert_human_approval`,
`HumanApprovalRequiredError` or `ProductionWriteNotAuthorizedError` at all --
asserted against its own source by a test. `GET /api/loops` is read-only; there
is deliberately no loop-specific write endpoint, because starting/stopping a
loop already has one (`POST /api/start` and the control-plane verbs, both behind
GUI-19's per-session token gate). Every emitter is best-effort: a telemetry
failure records `LOOP_TELEMETRY_EMIT_FAILED` and never turns a real routing
decision into a crash.

Proven by `dv_harness_tests/test_loop_telemetry.py` (37 tests) and
`dv_harness_tests/test_dashboard_loop_card.py` (8 tests) -- every event driven
out of a REAL `DVHarness.loop()` over the REAL shipped `main_graph.json` with
the REAL `command_migration_integrity_gate.py` subprocess, never by writing an
events.jsonl line by hand, and the card driven over real HTTP against the real
dashboard server. The negative controls are what give them power: a real gate
PASS is the positive control for LOOP_CONVERGING against the failing fixture's
LOOP_NO_PROGRESS; a real four-day flat coverage curve (written by the REAL
`dashboard.append_coverage_history_sample()` into a REAL DuckDB evidence store)
produces LOOP_PLATEAU_DETECTED while a real rising curve produces none; a
project with no evidence database emits no plateau verdict at all; and a loop
that really CLOSED is not reported as resumed by the next session. The
`LOOP_SUCCESS` test reaches a real `overall_status == CLOSED` through a real
SIGNOFF whose human-approval requirement is SATISFIED through the real
`ControlPlane.approve()` -- and the approval's per-PASS consumption is asserted,
not worked around. Nothing in either file runs a build, a regression or an LSF
submission.

**Disclosed residual**: this is the VERIFICATION CLOSURE loop's telemetry only.
The Project Learning and Capability Evolution loops emit no section-108 event --
`loop_contract.observe_all()` already reports the first `NOT_OBSERVABLE` (it is
observed per record, not per project) and the second is driven by human
`dv-harness research` / governance transitions rather than by an iterating
driver, so a `run_id`-scoped session does not exist for either. `CANCELLED` and
`STALE` have no producer and say so (`LOOP_STATE_WITHOUT_EVENT_REASON`), because
`derive_loop_state()` never returns them and section 97's stale detection is not
built. There is also no `dv-harness` CLI verb: the front doors are
`GET /api/loops` (the card) and `python -m dv_harness.loop_telemetry
names|events|rows|show`, both through one shared `execute_verb()`.


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


## Multi-User Coordination Conflict Detection (2026-09-06, section 239)

Spec section 239 ("MULTI-USER COLLABORATION") closes with two rules: "Do not use chat history as
the coordination mechanism" and "Concurrency conflicts remain explicit." The TRANSPORT and
AUTHORIZATION half of its list was already real and is deliberately untouched here --
`USAGE_MULTI_USER_SAFETY.md`'s standing policy (including the "never share a `--project-root`" rule),
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
three) REAL, SEPARATE project roots in the layout `USAGE_MULTI_USER_SAFETY.md` prescribes, each
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

## Subsystem Verification Contract Aggregator (2026-09-06)

A subsystem's verification truth -- which spec/DUT/TB it was verified against, which protocols/interfaces it exercises, what its requirements say, its vPlan/test/coverage correspondence, whether regression passed, whether SIGNOFF happened and against what frozen baseline, which evidence and reproducibility capsules back it, which waivers apply -- already existed as real, separately-queryable facts across `env_manifest.py`, `requirement_contract.py`, `golden_scenario.py`, `signoff_export.py` and `waiver_store.py`. Nothing assembled them into ONE record; two audits of the same project could describe a subsystem's "verification contract" differently even from identical underlying facts.

`dv_harness/subsystem_contract.py` is that assembly, and it is a pure aggregator: every field is read through an already-real function this repo ships, never re-derived. `spec_version`/`dut_sha`/`tb_sha` come from `signoff_export.capture_baseline()` (LIVE, not the frozen copy -- that function is already section 238's tested reader for these three identities). `protocols`/`interfaces`/`vplan_tests_coverage` come from `env_manifest.load_env_manifest()` + `summarize_for_blackboard()` (the same prompt-sized summary the `env_manifest` Blackboard topic already carries): `protocols` is the distinct `vip_type` values off `vip_config.vip_instances`, `interfaces` is those instances' own `instance_path` bindings, and `vplan_tests_coverage` is `env_topology.testplan_correspondence` verbatim with its own COMPUTED/PARTIAL/NOT_AVAILABLE status. `requirements` goes through `requirement_contract.execute_verb()` over a caller-named or conventionally-located requirement-contract JSON file (this repo has no fixed producer path for that artifact yet, the same disclosed boundary `generation_readiness.py`'s Spec Parsing / Requirement IR row already states -- an absent file is reported `NOT_AVAILABLE` naming exactly what was checked). `regression` is `regression_reporter.load_jobs()` + `dashboard._lsf_summary()`, the same real per-job LSF summary `golden_flow_readiness.py`'s LSF Regression row already reads. `signoff` carries the real-time `signoff_export.read_signoff_stage_status()` PLUS -- only when one was ever recorded -- the frozen `signoff_export.load_freeze()` baseline and its `evaluate_freeze_invalidation()` verdict; a project that never froze a baseline reports `NO_SIGNOFF_FREEZE_RECORDED` rather than a live re-capture standing in for "the signoff baseline" section 238 names. `evidence_references`/`reproducibility_capsules` share one `golden_scenario._open_store()`-opened `EvidenceStore`: the former is the real `normalized_evidence` rows (same table/columns `golden_scenario._fetch_normalized_evidence()` reads, unfiltered here), the latter is `golden_scenario.evaluate_store_freshness()` -- the real capsule list AND its real FRESH/STALE/UNKNOWN verdict. `waivers` is `waiver_store.status_report()` EXPLICITLY (not `signoff_export`'s digest-only waiver capture), because this contract wants the full per-waiver DERIVED status (VALID/EXPIRED/REVALIDATION_REQUIRED/REVOKED/UNKNOWN, TH-7).

**Subsystem scope.** Naming `--subsystem` consults `environment_mode_router.read_registered_subsystem_entries()` -- the real registry `engine._persist_subsystem_registry_entry()` writes only on a gate-verified SIGNOFF PASS for that subsystem. A match narrows the manifest lookup to that entry's own `environment_manifest` path; no match records the honest, named `SUBSYSTEM_NOT_REGISTERED` and falls back to the project's own default `env.manifest.json` -- most subsystem-mode/IP-level projects never reach a registered SIGNOFF and still have a real single-environment contract worth assembling. Omitting `--subsystem` assembles the project-scope contract.

**`unknowns` is the honesty surface.** Every field that could not be assembled lands there as `{"field", "reason"}`, never silently dropped or defaulted to an empty-but-present value; `completeness` (`COMPLETE`/`PARTIAL`/`NOT_AVAILABLE`) is scored against the fixed `TRACKED_ASPECTS` denominator, and the subsystem-scope-resolution unknown (a fact about the REQUEST, not about a contract field) deliberately never inflates that count.

**Read-only, with one explicit write.** `assemble_subsystem_contract()` mints no `.dv-harness/` tree, `StateStore`, evidence database, or waiver ledger where none exists -- every reader it calls already honours that contract on its own (`default_manifest_path()` returns `None` rather than generating; `read_signoff_stage_status()` reads state.json with a plain `json.loads`, never `StateStore.load()`; `golden_scenario._open_store()` returns `None` for an absent evidence.duckdb; `waiver_store.status_report()` reports `NO_WAIVER_STORE` rather than minting a ledger). `write_subsystem_contract()` / the `snapshot` verb is a separate, explicit act that persists the record to `.dv-harness/subsystem_contract.json`; `assemble` never writes. Both share `execute_verb()` (0 COMPLETE, 1 PARTIAL, 2 NOT_AVAILABLE/usage error), exposed as `python -m dv_harness.subsystem_contract assemble|snapshot [--subsystem ...] [--manifest ...] [--requirements ...] [--db ...] [--json]`. No `dv-harness` CLI verb was added -- `cli.py` was concurrently in use by other parallel work this session, the same reason several recent modules (`signoff_export`, `waiver_store`, `dependency_supply_chain`) also stay `python -m` only. It DECIDES, ARBITRATES and WRITES NO GOVERNANCE STATE: no stage runs, no gate is invoked, no approval is minted, and there is deliberately no stage gate -- a gate that passed because a contract record existed, or failed because one did not, would be worse than none.

**A real, pre-existing defect was found (and NOT fixed, out of this task's scope) while wiring this in**: `signoff_export._capture_evidence_hashes()` indexes `EvidenceStore.query()`'s plain tuple rows (`fetchall()`) with string keys (`r["evidence_id"]`), which raises `TypeError` the first time a project's `normalized_evidence` table actually holds rows -- apparently never exercised by that function's own test suite, which only covers the empty/absent-database paths. `capture_baseline()` bundles all fifteen section-238 fields into one call, so this contract's use of it for `spec_version`/`dut_sha`/`tb_sha` would otherwise crash the whole assembly whenever real evidence exists. `assemble_subsystem_contract()` now wraps that call and degrades those three fields to a named `NOT_AVAILABLE` (citing the real exception) instead of raising -- proven by `test_capture_baseline_failure_degrades_to_not_available_never_crashes`, which reproduces the trigger with a real evidence row. The underlying `signoff_export.py` defect itself is unfixed and should be closed in a follow-up touching that file.

`dv-harness subsystem-contract` has no dashboard card and no graph node -- this is a REACHED capability (a real CLI/import caller exists), not a WIRED one.

Proven by `dv_harness_tests/test_subsystem_contract.py` (37 tests) against real producers throughout: a real schema-valid `env.manifest.json` (via `env_manifest.generate_and_write()` with a real vip_config dump + testplan_sources file), a real waiver via `waiver_store.record_waiver()`, a real DuckDB `EvidenceStore` carrying a real `vip_distill.distill_sim_log()` envelope and a real `golden_scenario` capsule, a real LSF job JSON, a real `signoff_export.freeze_signoff_baseline()` freeze, and a real `subsystem_environment_registry.json`. Negative controls: a bare/uninitialized root (every tracked aspect honestly `NOT_AVAILABLE`, nothing fabricated, no `.dv-harness/` tree created), a manifest present but schema-invalid, an overclaimed (COMPLETE-with-a-placeholder-field) requirement record surfacing as FAIL rather than being smoothed into PASS, an LSF job with no `dv_analysis_status` (LSF DONE is not DV PASS), an expired waiver reported `WAIVERS_NOT_VALID` rather than collapsed into `NOT_AVAILABLE`, an `evidence.duckdb` that exists but holds zero rows, no signoff freeze recorded, a subsystem name requested but never registered (falls back to the project manifest), and the `capture_baseline()` crash-resilience case above. Both CLI verbs are driven as real subprocesses with their exit codes asserted.

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

### pattern-ir-assembly: PatternIR assembly from a duck-typed ScenarioIR shape, with ordering-convention validation

`dv_harness/pattern_ir_assembly.py` assembles a `PatternIR` -- the `global`/`dut`/`fw_policy`/`vip`/`check` command lists that back a command.txt-shaped pattern -- from a generic, duck-typed ScenarioIR-shaped input, without importing `verification_intent_ir.py` or `vplan_artifact.py` (both owned by a concurrent batch). The five `PatternIR` layers map 1:1 onto `.claude/skills/CORE/pattern-architecture/SKILL.md`'s real vocabulary: `global` = `block`, `dut` = `branch_a*`, `fw_policy` = `branch_fw`, `vip` = `branch_b*`, `check` = verdict/`FINAL_CHECK`.

**What it will not invent.** `global_commands`/`dut_commands`/`fw_policy_commands` are accepted only as caller-supplied, already-evidenced pass-through content -- per `pattern-architecture/SKILL.md` section 5 point 8, that content must come from real DUT RTL/PHY docs, which this module has none of, so it never synthesizes any. The one derivation this module does make -- routing a ScenarioIR item's `stimulus`/`coverage_intent` fields to `vip` and its `checker` field to `check` by default (overridable per item via `layer_overrides`) -- is documented in the module as a stated structural convention, not a claimed fact read off any RTL/VIP source.

**Honest failure over guessing.** An item with none of `stimulus`/`checker`/`coverage_intent` present, a `layer_overrides` value naming an unrecognized layer, a caller-supplied command entry with no text, or a `declared_order` that names an unknown layer, omits one, or duplicates one, is reported into `PatternIR.unclassified` or as `ORDER_STATUS_AMBIGUOUS` -- never silently dropped or defaulted. A `scenario_ir` argument (or a declared items list inside it) whose shape cannot be iterated at all raises `PatternIrAssemblyError` with a distinct `reason` string, rather than being treated as zero items.

**Ordering validation, cited to the skill.** `validate_layer_ordering()` compares a project-declared alternate layer order against `DEFAULT_LAYER_ORDER = (global, dut, fw_policy, vip, check)` -- `pattern-architecture/SKILL.md` section 4's ordering that 'stays fixed in every real instance' -- and reports named, cited risks for deviations matching that skill's load-bearing rules: `GLOBAL_NOT_FIRST`/`DUT_BEFORE_GLOBAL` (block must complete before anything else starts), `FW_POLICY_AFTER_VIP` (branch_fw must launch before any branch_b* that could need it), `CHECK_BEFORE_VIP` (verdict must follow branch_b*'s join). Any other deviation still gets a named-but-generic `LAYER_ORDER_DEVIATION_UNCLASSIFIED` risk rather than silent acceptance. Independently of ordering, it flags section 2's central trap -- `join_any` on the branch_b* fork being safe only while branch_a* never returns on its own -- as `JOIN_ANY_WITH_BRANCH_FW` when branch_fw is known to exist as its own branch (citing the skill's USB job-98520 false-pass regression), `JOIN_ANY_BRANCH_FW_PRESENCE_UNKNOWN` when that fact is genuinely unknown, and `JOIN_ANY_REQUIRES_JUSTIFICATION` even when branch_fw is confirmed absent. `risks` can be non-empty even when the ordering `status` itself is `PASS`/`DEFAULT_ORDER_ASSUMED` -- callers must check `risks`, not only `status`.

Tested by `dv_harness_tests/test_pattern_ir_assembly.py` (20 tests): the positive path assembling a real 2-item enumeration-style fixture into all five layers with correct counts and preserved objective/port traceability; a `layer_overrides` case routing a field to a non-default layer; five negative controls (no-intent-fields item, unknown-layer override, three unrecognized `scenario_ir` shapes, a non-list `items` value, a command entry missing text); and eleven ordering/join-mode tests covering `PASS`/`AMBIGUOUS_DECLARED_ORDER`/`DEVIATION_RISK`, every named risk, and all three presence states of the join_any trap. Run: `python -m pytest dv_harness_tests/test_pattern_ir_assembly.py -q`.

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


## Intake State: One Per-Field Record Joining Manifest + Decisions + Bind Tiers (2026-09-06)

`dv_harness/intake_state.py` answers "what does this project's intake actually know about field X, and from where" as one `IntakeFieldRecord` per field -- `{value, source, confidence, status, last_validated, owner}` -- joining three real sources that previously had to be read separately: env.manifest.json's own per-layer `status`/`reason` (`env_manifest.py`), a real `question_queue.QuestionQueueStore.find_decision()` (read-only; this module never files or answers a question itself), and `connectivity.py`'s `BindTier` vocabulary for per-bind-entry confidence. Status is one of AUTO_RESOLVED / USER_CONFIRMED / PARTIAL / CONTRADICTED / MISSING / BLOCKED / UNKNOWN / NOT_APPLICABLE -- a human answer (`question_queue.HUMAN_DECISION_SOURCE`) always outranks the harness's own Tier-2 auto-assumption, and a Tier-2 guess never downgrades a fact already computed from a real source; a field where a human's filed answer disagrees with an already-computed value reports CONTRADICTED rather than being silently overwritten as if the two agreed.

`evaluate_uvm_generation_ready()` is a hard refusal gate over six named blocking categories -- DUT boundary, VIP unresolved, active-driver conflict, critical bind, build env, known-PASS test -- folded worst-wins per category (`IntakeState.category_status()`); a category with zero fields recorded at all folds to MISSING, never "ready by omission". `already_resolved(intake_state, field_name)` is the do-not-ask helper: a caller should check this BEFORE calling `question_queue.QuestionQueueStore.add_question()` for a field, since this module never files questions itself.

Three of the six blocking categories are deliberately duck-typed rather than imported, each documented with its intended real producer in the module docstring: `dut_boundary` accepts `phy_boundary.py`'s own `{status, bind_decision: {bindable, mount_layer, rationale}}` shape without importing that module; `active_driver_conflicts` accepts a generic `{resource, status, reason}` list standing in for `system_resource_inventory.real_cross_subsystem_findings()`; `known_pass_tests` accepts a generic `{test_name, verdict, reason}` list standing in for `golden_scenario.py`'s recorded capsules -- not imported because `golden_scenario.py` was, at the time this module was built, one of four files a separate concurrently-running batch was editing. `connectivity.py` and `env_manifest.py` are imported directly for their real vocabularies (`BindTier`/`GateStatus`, layer `status`/`reason`), since neither was part of that concurrently-edited set.

Deliberately bounded: this module JOINS and REPORTS only. It files no question, runs no gate script, writes no state/blackboard/approval record, and holds no stage gate of its own -- `evaluate_uvm_generation_ready()` only refuses or allows a caller's next action.

Proven by `dv_harness_tests/test_intake_state.py` (41 tests): env.manifest layers are built through the REAL `env_manifest.py` producer functions over real fixture `register_map.json`/`soc_arch_map.json`/`testplan_sources.json` (including a genuine register/address-map base-address disagreement and a genuine broken vPlan test reference, both producing real CONTRADICTED verdicts, not fabricated ones); DUT-boundary facts are the real `phy_boundary.classify_boundary()`/`decide_bind_location()` output for both a PARALLEL (bindable) and a SERIAL (BLOCKED) case; bind-tier facts are classified through real `connectivity.BindTier` values across T1-T4, including a negative control where a fabricated (non-`human_answer`) confirmation source still BLOCKS; question_queue decisions are produced by driving a real `QuestionQueueStore` through its real `add_question()`/`answer_question()` API, never a hand-written decision record. Negative controls prove absent evidence never reads as resolved: a state built from nothing refuses on all six blocking categories, and flipping just one category back to BLOCKED in an otherwise-fully-resolved state still refuses generation as a whole.

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

## vPlan Artifact: Schema + Hierarchy + 9-Dimension Completeness + 15-Value Gap Taxonomy (2026-09-06)

A vPlan (verification plan) is a hierarchy of rows -- sections/features (containers) and leaf verification items -- each of which should carry a requirement link, a verification method, coverage/checker/test linkage, an owner and a priority. Nothing in this repo turned that shape into a checkable artifact: a repo-wide grep for `vplan_artifact`/`VPlanCompletenessReport` matched nothing, and the closest existing mechanism, `env_manifest.py`'s `testplan_correspondence`, answers a narrower, different question -- does a name-matched join of an EXISTING testlist/vPlan/coverage model line up -- over a project's own real `env.manifest.json`. It has no notion of vPlan HIERARCHY, no independent per-dimension status, and no gap taxonomy or next-best-action wiring.

`dv_harness/vplan_artifact.py` is that schema, hierarchy and analysis. It reuses rather than re-mints: `subsystem_discovery`'s READY/PARTIAL/BLOCKED/UNKNOWN readiness words (the same four `golden_flow_readiness.py`/`generation_readiness.py` already reuse), `verification_strategy.STRATEGIES` (SIMULATION/FORMAL/PSS/EMULATION/FPGA_PROTOTYPE) as the known verification-method vocabulary, `memory.CORNER_CASE_RISK_TIERS` (P0..P3) as the priority vocabulary (the same scale `requirement_contract.py`'s own `priority` field already uses), `inference.next_best_action()` through a NEW `VPLAN_GAP_ACTION_CATALOG` (the domain-neutral Gap -> Next-Best-Action engine section 10 forbids re-implementing), and `connectivity.render_markdown_table()` for the optional matrix render.

**Genuinely new**: the vPlan row schema (`validate_vplan_row`/`validate_vplan_document`, fail-closed via `VPlanArtifactValidationError` for a STRUCTURAL defect only); the hierarchy builder (`build_vplan_hierarchy`, a single-parent-pointer tree-walk detecting duplicate ids, orphan parent references and cycles as reported gaps, never raised, since these are semantic-but-shape-valid facts); the NINE independent completeness dimensions (`analyze_vplan_completeness`/`VPlanCompletenessReport`) -- HIERARCHY_INTEGRITY, REQUIREMENT_COVERAGE, VERIFICATION_METHOD_ASSIGNMENT, COVERAGE_MODEL_LINKAGE, CHECKER_LINKAGE, TEST_STIMULUS_LINKAGE, OWNERSHIP_ASSIGNMENT, PRIORITY_ASSIGNMENT, INTENT_CROSS_CONSISTENCY -- each scored, gapped and reasoned about independently and NEVER averaged/weighted/folded into one number, the same non-collapsing-status discipline `requirement_contract.py`'s five-value status vocabulary and `golden_flow_readiness.py`'s per-row Status column already hold; and the FIFTEEN-value gap taxonomy (`GAP_TAXONOMY`), each code mapped to exactly one dimension (`GAP_TO_DIMENSION`) and a severity (`GAP_SEVERITY`: BLOCKED for a structural/false-claim defect such as a dangling reference or a cycle, PARTIAL for an honest absence such as an unmapped requirement or a missing owner) -- both mappings held total by `assert_gap_taxonomy_total()` at import time, so a future edit that adds a gap without wiring it fails a test rather than silently reporting `UNKNOWN` severity.

**Why this takes generic dict/list input rather than importing a real producer.** Per this batch's file-safety scope, this module must not import `spec_intelligence.py` or `verification_intent_ir.py` -- both are owned by OTHER, concurrently-running tasks in this same batch. `vplan_rows`, `requirements` and `verification_intents` are therefore accepted as plain lists of dicts, documented at the top of `analyze_vplan_completeness()` as the shape either sibling module's real output would need to be reduced to (e.g. `{"id": rec.requirement_id}` / `{"id": rec.intent_id, "verification_method": rec.method}`) to feed this analysis with no change to this module's own logic once either lands.

**Deliberately bounded, stated rather than implied closed.** It reads a vPlan RECORD (plus optional requirement/intent records); it does not parse a specification, does not extract vPlan rows from prose, and does not check a vPlan against RTL, a register map, or a real coverage database. Coverage/checker/test-stimulus linkage (dimensions 4-6) is evaluated ONLY over leaf rows whose declared `verification_method` is coverage/test-relevant (`SIMULATION`/`EMULATION`/`PSS` for coverage+checker; `SIMULATION`/`EMULATION` for test-stimulus, since PSS generates its own scenarios rather than citing a pre-existing test) -- a `FORMAL`-only vPlan reports those three dimensions honestly `UNKNOWN` with zero applicable rows rather than a fabricated `READY`. `requirements`/`verification_intents` cross-checks report `UNKNOWN` with a real reason when the caller supplies `None`, never a silent clean pass. It DECIDES, APPROVES and RUNS nothing: no stage executes, no gate script is invoked, no file is written, and there is deliberately no `STAGE_GATES` entry -- a completeness report is an input to a human's vPlan-review decision, exactly like `golden_flow_readiness.py`'s and `generation_readiness.py`'s own matrices. `ControlPlane.approve()`, `policy.can_signoff()`, `assert_human_approval()` and the PR-only main/master governance are untouched and unreferenced.

Proven by `dv_harness_tests/test_vplan_artifact.py` (37 tests): the clean positive path across all 9 dimensions over a fully-populated fixture (two container sections, three leaves spanning SIMULATION/FORMAL/EMULATION); taxonomy/dimension totality self-checks; and real negative controls for every one of the 15 gap codes -- a duplicate row id, an orphan parent reference, a 3-node `parent_id` cycle (all `BLOCKED` on `HIERARCHY_INTEGRITY`), a dangling requirement/intent reference (`BLOCKED`, proven distinct from the honest `PARTIAL` of an unmapped requirement/unreferenced intent), an unrecognized `verification_method`, the FORMAL-only honest-`UNKNOWN` case for dimensions 4-6, a missing owner/priority, an unrecognized priority value, a row/intent `verification_method` contradiction, next-best-action wiring returning exactly the present gap codes with `source == "vplan_artifact"` and never touching the filesystem, schema-validation rejections (non-mapping row, missing id, non-string-list field, non-list document), and the empty-vplan case reporting `UNKNOWN` -- never a fabricated `READY` -- across every one of the 9 dimensions.

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

## Consolidated KPI/Benchmark Report: One Module, Real Producers Only (2026-09-06)

Several near-duplicate KPI trackers were implicit across intake, spec-to-signoff, spec-to-vplan and golden-scenario/USB-benchmark surfaces: `question_queue.py` already computes 4 real intake metrics behind its own verb, `trend_analysis.py` already detects PASS->FAIL regressions and same-SHA flip-flops behind its own report, and `signoff_export.py` already evaluates frozen-baseline invalidation behind its own verb -- but nothing assembled "how healthy is this harness's own verification WORKFLOW" (as opposed to one project's DUT) into one report. `dv_harness/consolidated_kpi_benchmark.py` is that one cross-cutting module, and it computes NOTHING a real producer does not already own -- it reads, counts and reports.

**8 KPIs, each naming its real producer.** `question_queue_self_resolve_rate` reuses `QuestionQueueStore.compute_metrics()` verbatim (bundling its 3 siblings -- blocking-questions/week, repeat-question rate, assumption-overturn rate -- since they are one real computation over one store). `repeated_question_count` is a plain count over that same module's own `list_questions()` raw records (total asks minus distinct question_keys) -- new arithmetic, but a COUNT over raw data, never a re-derivation of `question_queue.py`'s own Tier/self-resolve classification. `time_to_first_pass` reads real section-108 loop telemetry (`loop_telemetry.loop_events()`): the elapsed time from a real `LOOP_STARTED` to the first `LOOP_VERIFY_COMPLETED` carrying `verdict == Status.PASS.value`, per real `run_id`. `false_pass_count` is `trend_analysis.detect_pattern_regressions()`'s own `SAME_GIT_SHA_PASSED_AND_FAILED` reason over the real `evidence_db.regression_verdict_history` table -- a real existing signal that an earlier PASS did not guarantee its own property. `false_ready_count` is `signoff_export.evaluate_all_freezes()`'s own `INVALIDATED` count -- a frozen (declared-READY) signoff baseline later proven wrong by real post-freeze evidence, the closest real analog to "false-READY" this codebase has.

**Honest `NOT_MEASURED`, verified by direct search rather than assumed.** `ir_extraction_accuracy`, `manual_edit_count` and `human_engineering_time` are always reported `NOT_MEASURED`: a repo-wide grep confirmed no module compares an extracted requirement/IR against a ground-truth-labeled extraction (only `requirement_contract.analyze_requirement_contract_set()`'s self-consistency status and `vplan_baseline`'s content-identity version exist, neither of which is an accuracy measurement), and no keystroke/diff-authorship tracker or engineering-time tracker exists anywhere. Each carries its real missing-producer reason rather than a fabricated number.

**The honesty pattern is `confidence_calibration.py`'s** (read for the pattern, no code imported or copied): four distinct statuses -- `MEASURED` / `NOT_MEASURED` / `INSUFFICIENT_HISTORY` / `NOT_AVAILABLE` -- checked at import to share no token with `dv_harness.models.Status`. A rate-shaped KPI below `MIN_SAMPLE_FOR_RATE = 10` (the same "smallest N at which 1/N <= 0.1" derivation) or a timing KPI below `MIN_RUNS_FOR_TIMING = 3` reports `INSUFFICIENT_HISTORY` rather than a rate/median computed off a couple of samples. Every KPI in `KPI_NAMES` always has a row in the report, MEASURED or not -- never silently omitted.

**Reading is never a mutating act.** `QuestionQueueStore`/`EvidenceStore` are opened read-only or not constructed at all when their backing file is absent (proven: a bare project gains zero files/directories from a report); no build, gate, approval, memory, waiver or Blackboard record is written; there is deliberately no stage gate -- a gate that passed on a KPI nobody actually measured would be worse than none. `ControlPlane.approve()`, `policy.can_signoff()` and the PR-only main/master governance are untouched and unreferenced. Per this task's file-safety scope, `dv_harness/gates.py` and `dv_harness/cli.py` were not touched and no entry is proposed for either; the front door is `python -m dv_harness.consolidated_kpi_benchmark {names,report,show}`.

Proven by `dv_harness_tests/test_consolidated_kpi_benchmark.py` (29 tests), every fixture built through the real owning module (`QuestionQueueStore.add_question()`, `loop_telemetry.emit()` through a real `StateStore`, `EvidenceStore.insert_regression_verdict()`, `waiver_store.record_waiver()`/`revoke_waiver()`, `signoff_export.freeze_signoff_baseline()`) -- nothing hand-written into a JSON/JSONL file to look like real evidence. Each KPI has a core positive path (cross-checked against an independent call to the real underlying producer, e.g. the self-resolve-rate KPI's value asserted equal to a directly-called `compute_metrics()` result) plus real negative controls: zero real events (`NOT_AVAILABLE`), too few real events (`INSUFFICIENT_HISTORY`), and a genuinely-clean history reporting a real zero rather than skipping the KPI. The headline test the task requires, `test_ir_extraction_accuracy_is_always_not_measured_never_fabricated` (plus its two siblings for manual-edit-count and human-engineering-time), asserts a KPI with no real producer reports `NOT_MEASURED` with `value is None` on every call, never a fabricated number.

## Protocol Compliance Aggregation: Scoreboard PASS Never Outranks a Real Checker Violation (2026-09-06)

This harness has no formal protocol-checker TOOL, and `dv_harness/protocol_compliance_aggregation.py` does not build one -- verified before writing anything: `vip_distill.py`'s real `SOURCE_KINDS` is exactly `("sim_log", "job_record", "fsdbreport", "combined")`, with no `"protocol_checker"` kind, and none of its `detail` dicts (epilogue/signatures/counts/lsf_status/sim_status/topic/fsdbreport) ever carries a checker-specific verdict field; `dv_harness/uvm_generator/protocol_model_layer.py` -- the other real module this task named to read -- carries no `verdict`/`checker`/`PASS`/`FAIL`/`violation` token at all (it compiles LTSSM state-transition legality into SVA assertions; it produces no runtime checker RESULT). So a real protocol-checker verdict, distinct from the scoreboard verdict `vip_distill.py` already normalizes, is not something this repository's own evidence pipeline produces today, and this module says so rather than inventing one.

What it builds is only the AGGREGATION RULE: given a stage's real scoreboard PASS/FAIL verdict (the real, already-normalized `vip_distill.py` envelope's own `verdict` field, read via `evidence_db.py`'s real `normalized_evidence` table -- reusing its real column list rather than re-parsing evidence a second way) plus, IF a real protocol-checker verdict is present in the SAME evidence set, that verdict too -- **a scoreboard PASS alongside a real protocol-checker violation is still an overall FAIL**, and **absent protocol-checker evidence reports `NOT_CHECKED`, distinct from `CLEAN`/`PASS`, never assumed clean**. `_decide_overall()`'s priority order: a real checker FAIL overrides everything (including a scoreboard PASS and even an absent scoreboard); otherwise a scoreboard FAIL is overall FAIL; no scoreboard evidence at all is `NOT_AVAILABLE`, never a default PASS; either side carrying a real-but-unrecognized verdict string is `UNKNOWN`, never rounded to PASS or FAIL; scoreboard PASS + checker PASS is PASS; scoreboard PASS + checker `NOT_CHECKED` is still PASS, but the report always carries `protocol_checker_status: "NOT_CHECKED"` alongside it so it can never be read as a verified-clean protocol result.

`SCOREBOARD_PASS_VERDICTS`/`SCOREBOARD_FAIL_VERDICTS` cite the same real `vip_distill.py` verdict vocabulary `golden_scenario.py`'s own `PASS_VERDICTS` already documents, independently restated rather than imported: `golden_scenario.py` is one of the files a separate, already-running batch of agents is concurrently editing, and this module deliberately imports neither it nor any other file under concurrent edit in either running batch. `load_normalized_evidence_rows()` queries the real `evidence_db.py` `normalized_evidence` table directly (positional-tuple results zipped against the real, verified column order, avoiding a known real fetchall()-as-dict indexing defect disclosed elsewhere in this codebase) and re-shapes rows back into the real `vip_distill.py` envelope dict shape. `extract_verdicts_from_evidence_set()` is duck-typed over any sequence of such dicts, so it consumes evidence in memory, evidence read back from a real database, or -- once a real protocol-checker producer is ever built -- that producer's own output, without importing a module that does not exist yet. `PROTOCOL_CHECKER_DETAIL_KEYS` (`protocol_checker_verdict`/`vip_checker_verdict`/`checker_verdict`, read from a normalized_evidence row's own free-form `detail` dict) is a disclosed, honest EXTENSION POINT -- explicitly not a claim that any real producer writes one today.

**Deliberately bounded, and stated rather than implied closed.** (1) No formal protocol-checker tool exists or was built here, per this task's own instruction -- the module aggregates whatever real checker evidence a future tool might one day produce, and honestly reports `NOT_CHECKED` until one does. (2) There is deliberately no stage gate and no `gates.py`/`cli.py` change -- this task's scope was the aggregation module alone; a `dv-harness` verb or `STAGE_GATES` entry, if ever wanted, is for a separate integration step. (3) It decides and authorizes nothing beyond reporting: no approval/governance mechanism is referenced.

Proven by `dv_harness_tests/test_protocol_compliance_aggregation.py` (20 tests) against a REAL DuckDB `EvidenceStore` and REAL `vip_distill.distill_sim_log()` envelopes for both a PASSING and a FAILING synthetic sim.log in this project's own documented FINAL CHECK epilogue format -- never hand-typed evidence shaped to look real. The central proof records a real scoreboard-PASS row and a checker-violation row (this repo's honest extension-point shape) against the SAME `job_id` in one real `evidence.duckdb`, and asserts the aggregation reads back out as an overall FAIL. Negative controls: no scoreboard evidence never reads as PASS; an unrecognized scoreboard or checker verdict string reads UNKNOWN, never PASS; a real checker FAIL overrides even an absent scoreboard; fsdbreport rows (which vip_distill.py's own docstring says carry no verdict concept) never contribute a scoreboard verdict even if one is stray-present; an unrelated job's evidence never bleeds into another job's aggregation; and a bare, just-initialized evidence database reports `NOT_AVAILABLE`, never a false clean PASS.

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


## Verification Intake Contract: the Whole-Project Lifecycle + INTAKE_READY Conjunction (2026-09-06)

Every sub-domain intake mechanism in this project answers its own narrow question well (`env_manifest.py`'s 3-layer manifest, `question_queue.py`'s ask/decide lifecycle, `connectivity.py`'s bind-tier gate, `requirement_contract.py`'s per-requirement status, `golden_scenario.py`'s per-test freshness, `waiver_store.py`'s per-waiver status). Nothing sat one level above them and answered the capstone question a human actually has to ask before generation or signoff can begin: "across every domain intake touches, where is THIS PROJECT's intake right now, and is it actually ready?" A repo-wide grep for `VerificationIntakeContract`/`INTAKE_READY`/`intake_contract` before writing this module matched nothing executable.

`dv_harness/verification_intake_contract.py` is exactly two things, nothing more:

1. **A lifecycle state machine for the whole intake effort**, not any single domain's local state. Thirteen states in the task's own order -- `CREATED -> DISCOVERING -> CORRELATING -> QUESTION_PENDING -> USER_INPUT_RECEIVED -> VALIDATING -> CONFLICT -> PARTIAL -> BLOCKED -> READY_FOR_REVIEW -> BASELINED -> STALE -> REVALIDATING` -- with a real, closed `TRANSITIONS` graph enforcing legal moves (`assert_legal_transition()` on every transition; an illegal jump such as `CREATED` straight to `VALIDATING` raises `IntakeContractError("ILLEGAL_STATE_TRANSITION", ...)` naming the real legal next states). `READY_FOR_REVIEW` is explicitly non-terminal, per spec: it carries five outgoing edges (three send the contract back to earlier work -- `DISCOVERING`/`CORRELATING`/`VALIDATING` -- plus a fresh `QUESTION_PENDING` and forward approval to `BASELINED`). That idea is generalized rather than special-cased: `assert_no_absorbing_state()` runs at import time and proves EVERY state (not only `READY_FOR_REVIEW`) has at least one real outgoing edge -- even `BASELINED` has a real edge to `STALE`, so a baselined contract can be invalidated by a later spec/RTL/config change exactly the way `signoff_export.py`'s frozen baseline can (this module accepts that resulting `STALE` transition; it does not itself decide staleness -- that decision belongs to `golden_scenario.evaluate_freshness()`/`signoff_export.evaluate_freeze_invalidation()`, which this module deliberately does not import).

2. **INTAKE_READY: a conjunction of caller-named critical conditions, never an average.** `evaluate_intake_readiness(conditions)` takes a caller-assembled list of `{"name", "status"}` records (status one of `MET`/`UNMET`/`UNKNOWN`/`NOT_APPLICABLE` -- `MET`/`NOT_APPLICABLE` clear, `UNMET`/`UNKNOWN` both block, deliberately undistinguished: "this failed" and "we could not tell" are both reasons a human must not be told the project is ready). `ready` is `True` iff the blocking list is empty -- one single `UNMET`/`UNKNOWN` condition among any number of clean ones still reports `NOT_READY` naming that one condition, never diluted into a percentage. This is the same worst-wins, no-averaging discipline `golden_flow_readiness.combine_readiness()` already applies one row at a time ("BLOCKED is worse than UNKNOWN on purpose... must not be averaged away"), generalized here over an open-ended, caller-declared condition set rather than a fixed twenty rows -- which conditions exist is never hardcoded, since they come from other, separately-building modules (env manifest completeness, requirement contract completeness, connectivity bind-tier clearance, golden scenario freshness, waiver validity, VIP API provability, and others). An empty condition list reports `NOT_AVAILABLE` with `ready=False`, never a vacuous `READY` over zero conditions. A duplicate condition name, an unrecognized status, or a malformed record all raise `IntakeContractError` rather than being silently dropped or resolved by guessing.

**Deliberately bounded, and stated rather than implied closed.** This module imports NOTHING else from `dv_harness` -- proven by an AST-based test -- because it was built as the capstone of a batch in which several sibling intake modules (`intake_state.py`, `requirement_contract.py`, `golden_scenario.py`, `waiver_store.py`, and others) were concurrently in flux or on this batch's own never-touch list; every sub-domain fact is accepted as a generic, duck-typed parameter (a plain dict or list) rather than fetched by import. It never runs a stage, invokes a gate script, submits a build/regression/LSF job, or writes an approval/governance record -- `ControlPlane.approve()`, `policy.can_signoff()`, `assert_human_approval()` and the PR-only main/master governance are untouched and unreferenced in code (asserted by a tokenize-based test that strips this module's own explanatory docstrings before checking, since the docstrings legitimately name what this module does NOT do). It does not decide what a `CONFLICT` between two domains means or which side wins -- the same "ARBITRATION IS NOT HERE" boundary `requirement_contract.py` already draws for its own `CONTRADICTORY` status. It persists nothing to disk on its own: `VerificationIntakeContract` is a plain in-memory record; a caller decides how (or whether) to serialize it. There is deliberately no `dv-harness` CLI verb and no edit to `gates.py`/`cli.py`/`CLAUDE.md` -- the front door is `python -m dv_harness.verification_intake_contract states|transitions|evaluate`, the same ad hoc fallback several sibling 2026-09-06 modules already use.

Proven by `dv_harness_tests/test_verification_intake_contract.py` (34 tests): a full realistic lifecycle traversal exercising every real loop this project's own intake work actually takes (a `CONFLICT`, a `PARTIAL`, a `BLOCKED`, a human sending a reviewed `READY_FOR_REVIEW` contract back before approving, and a `BASELINED` contract going `STALE` and being `REVALIDATED`); a mutation-style test proving the import-time transition-table guards have real detection power (a state popped from the table, a state made absorbing, a target pointed at a non-existent state each trip the guard that names that specific defect); the headline no-averaging proof (99 clean conditions plus 1 `UNMET` still reports `NOT_READY` naming exactly that one condition); 8 further INTAKE_READY negative controls; the `require_intake_ready` opt-in gate on the `READY_FOR_REVIEW` edge; and CLI subprocess tests for all three verbs and all three exit codes.

## Intake Question Priority: Ask-Gating Table, Next-Best-Question Ranking, and Batching (2026-09-06)

Three small, related mechanisms an intake flow needs whenever a real 3-tier ask-a-human queue (`question_queue.py`) accumulates pending questions faster than a human can answer them, and nothing in this repo decided any of the three: whether a given pending question is even worth asking given what the harness already believes and what getting it wrong would cost, which of several worth-asking questions to surface FIRST, and how to group several LOW-stakes questions into one round without ever letting a high-stakes one hide inside a batch. `dv_harness/intake_question_priority.py` is all three, and it deliberately does not import `question_queue.py` at all -- this task's own scope named that boundary explicitly, so pending-question data arrives as a generic list of dicts and every fact this module needs (confidence, criticality, the four ranking factors, a declared topic key, an `architecture_defining` flag) is read directly off the caller's own dict rather than coupled to that module's schema.

**(a) The gating table is 16 explicit cells, not a computed risk score.** `CONFIDENCE_LEVELS = (LOW, MEDIUM, HIGH, UNKNOWN)` crossed with `CRITICALITY_LEVELS = (MINOR, MAJOR, BLOCKER, UNKNOWN)` -- a fourth "we do not honestly know" value on both axes so an absent or unrecognized fact is never silently guessed into a numeric axis. `GATING_TABLE` spells out all 16 `(confidence, criticality) -> (ASK|DO_NOT_ASK, reason)` pairs by hand, matching this task's own two worked examples verbatim: `(HIGH, MINOR)` and `(HIGH, MAJOR)` are the only "non-critical" DO_NOT_ASK cells, and `(MEDIUM, BLOCKER)` is ASK. Two deliberate asymmetries carry real weight: BLOCKER criticality is ASK at every confidence level including HIGH (an architecture-defining decision is confirmed regardless of how sure the harness already is, the same posture `connectivity.py`'s Bind-Location Tier 3/4 rules already take), and UNKNOWN on either axis is always ASK -- an unclassified criticality is never read as evidence it is safe to skip, and an unclassified confidence is never read as evidence the harness is sure. `gate_question()` normalizes a raw value to UNKNOWN (flagged `*_recognized: False`) rather than raising, and `gate_pending_questions()` runs it over a whole list.

**(b) Next-best-question ranking is exactly the stated formula, and nothing this module invents.** `score_question()` computes `blocking_value * downstream_impact * expected_confidence_gain / user_effort` over four caller-supplied numeric factors -- their real meaning and measurement is entirely the caller's, per this task's own instruction not to invent how they are measured. A missing factor, a non-numeric one (a `bool` is explicitly rejected, since it is a Python `int` subclass), a negative weight, or a `user_effort` that is not strictly positive (the divisor) all report `UNVERIFIABLE` naming the real bad field, never a placeholder score. `rank_questions()` sorts the scorable subset descending (question-id tie-break for determinism) and reports the unrankable subset alongside it, never dropped.

**(c) Batching groups only what was explicitly declared safe to group.** `classify_batch_risk()` treats ONLY an explicitly-declared `MINOR` criticality (with no `architecture_defining: true` flag) as LOW/batchable; BLOCKER, MAJOR, an explicit `architecture_defining` flag, and an absent/unrecognized criticality are all HIGH risk -- deliberately stricter than the gating table's own MAJOR handling, because merging several questions into one round changes what a human reads together. `build_question_batches()` groups LOW-risk questions sharing a caller-declared topic key (`topic`/`related_topic`/`related_group`/`group_key` -- never an inferred/NLP-derived relatedness, which this module does not attempt), splits an oversized group deterministically when `max_batch_size` is given, and places every HIGH-risk question in a batch of exactly one regardless of topic overlap -- the property this task's "NEVER batches an architecture-defining/high-risk question with anything else" rule requires, and it is asserted directly (including the case where the same topic is shared with an otherwise-batchable MINOR question).

`analyze_pending_questions()` composes all three in the natural order (gate, then rank and batch only the to-ask subset -- a DO_NOT_ASK question is never scheduled at all), with `render_report_text()` and a `python -m dv_harness.intake_question_priority` front door (no `dv-harness` CLI verb was wired and neither `cli.py` nor `gates.py` was touched, per this batch's file-safety scope).

**Deliberately bounded.** It reads no file, writes no state, files no question, answers no question, runs no build/regression/LSF job, and touches no approval/governance mechanism -- it computes three small decisions over data the caller supplies and nothing else. It does not decide what a question's confidence/criticality/four ranking factors/topic actually ARE; those are read verbatim off the caller's dict, exactly as `question_queue.py` itself is the authority on its own records.

Proven by `dv_harness_tests/test_intake_question_priority.py` (35 tests): the gating table's full behavior including both of this task's own worked examples, BLOCKER-always-asks-regardless-of-confidence, UNKNOWN-on-either-axis-always-asks, and unrecognized-value normalization; the ranking formula plus six negative controls (missing factor, non-numeric, boolean-rejected, zero/negative `user_effort`, negative weight, unrankable-never-dropped); the batching rule's grouping plus negative controls (a BLOCKER question never merged even sharing a topic, an `architecture_defining`-flagged MINOR question never merged even sharing a topic, a topic-less LOW-risk question never guessed into a group, MAJOR/UNKNOWN questions never grouped even sharing a topic, `max_batch_size` splitting in original order, a non-positive `max_batch_size` refused); the integrated pipeline; and three real CLI subprocess invocations asserting exit codes 0/1/2.

**Disclosed residual**: this is a standalone, non-wired module by design -- no `dv-harness` CLI verb, no graph node, no stage gate, and no import of `question_queue.py`'s real `QuestionQueueStore`. A caller integrating it with the real queue must translate that store's records into the generic dict shape this module expects itself. The four ranking factors' real-world measurement is entirely undefined by this module, as instructed. "Closely related" for batching is a caller-declared topic-key match only; no semantic/NLP relatedness is computed.

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

## Source Authority: Conflict-Type Taxonomy (2026-09-06)

`source_authority.resolve_conflict()` decides WHICH VALUE wins when two sources disagree; it never says WHAT KIND of disagreement this was. Two conflicts that both resolve `RESOLVED` -- or both land at `UNDECIDABLE_SAME_AUTHORITY` -- can be entirely different SHAPES of problem: two controller docs disagreeing with each other is a documentation-staleness question; a register file disagreeing with the RTL decoder is a regmap-vs-silicon question; a VIP's shipped example disagreeing with its own user guide is a VIP-internal-consistency question. Nothing anywhere named that shape, so two audits of the same conflict history could each describe "what kind of conflicts this project has" differently from identical underlying records.

A purely additive extension to `dv_harness/source_authority.py` (no other file touched, per this gap-closure's own scope) adds exactly that: a 10-value classification layer over the source TYPES a conflict names, layered on top of -- and never changing the meaning of -- the existing 9-level `AUTHORITY_ORDER`/`resolve_conflict()`/`escalate_conflict()` machinery.

**The vocabulary** (`CONFLICT_TYPES`): `DOC_DOC_CONFLICT`, `DOC_RTL_CONFLICT`, `REGISTER_RTL_CONFLICT`, `GUIDE_REGISTER_CONFLICT`, `PHY_SPEC_MODEL_CONFLICT`, `VERSION_CONFLICT`, `CONFIGURATION_CONFLICT`, `COMMAND_TASK_CONFLICT`, `VIP_DOC_SOURCE_CONFLICT`, `UNKNOWN` -- held closed against drift by `assert_conflict_type_vocabulary_is_closed()`, which runs at import time and fails if a declared `CONFLICT_TYPE_*` constant's value is not in the tuple.

**Why it needs a wider vocabulary than the 9-level order itself.** Four of the ten values (`PHY_SPEC_MODEL_CONFLICT`, `VERSION_CONFLICT`, `CONFIGURATION_CONFLICT`, and the ad hoc half of `COMMAND_TASK_CONFLICT`) name source shapes the conflict-authority order has no rank for at all -- a PHY electrical model, a spec/datasheet document, a tool/VIP version string, a configuration/variant value. `SourceClaim.__post_init__` correctly refuses to rank any of those (there is no level to give a PHY model in the 9-level order), so a genuine PHY-model-vs-spec disagreement can never reach `resolve_conflict()` as a real claim pair -- but it is still a real, nameable conflict. `classify_conflict()` therefore accepts TWO record shapes: a real `resolve_conflict()`/`escalate_conflict()` record (reading each claim's own `source`, always one of the 9 `AUTHORITY_ORDER` ids), or a lighter ad hoc `{"source_a": ..., "source_b": ...}` / `{"sources": [...]}` record for a disagreement the 9-level order was never meant to rank.

**Classification is by source TYPE alone, never by claim content.** `normalize_conflict_source_kind(name)` maps a source name onto one of 13 broad "kinds" -- each of the 9 real `AUTHORITY_ORDER` ids resolves to exactly one kind (checked equal to `{s.id for s in AUTHORITY_ORDER}` by test, so a future 10th authority level cannot go unclassified), and 4 extra kinds (`phy_model`/`spec`/`version`/`configuration`) exist only in this layer, with their own alias table folded through the SAME `_key()` normalization every `AUTHORITY_ORDER` alias already uses. An unrecognized source raises `UNKNOWN_CONFLICT_SOURCE_KIND` rather than silently classifying `UNKNOWN` -- the same "never let a typo hide behind the taxonomy's own honest unknown value" discipline `normalize_source()` already applies to the conflict-authority order itself.

`classify_conflict_type(source_a, source_b)` looks up the unordered kind pair in a fixed table and returns `UNKNOWN` for any pair the table does not name (e.g. `simulation_result` vs. `controller_doc`, or two `existing_testbench_bind` claims) -- naming a conflict's type WRONG is worse than admitting it does not fit one of the nine named shapes. `classify_conflict(conflict)` is the record-level entry point: it classifies a `NO_CONFLICT`-verdict record too (the taxonomy is about which two source types were being COMPARED, not whether they agreed), and refuses -- rather than guesses -- a record naming more than 2 distinct source types (the same 2-3-sides pairwise boundary `escalate_conflict()` already draws for the question-queue schema), a record matching neither accepted shape, a record with no sources at all, or a non-dict.

Proven by 31 new tests appended to `dv_harness_tests/test_source_authority.py` (68 total, all 37 pre-existing tests untouched and still passing): vocabulary closure, `AUTHORITY_ORDER`-id-to-kind completeness, all 9 named pairs (via both `AUTHORITY_ORDER`'s own aliases and the extra-kind alias table, and order-independence), 4 negative controls for unrelated-but-recognized pairs reading `UNKNOWN` plus an unrecognized-source refusal, `classify_conflict()` driven against a REAL `resolve_conflict()` record at all three of its real verdicts (`RESOLVED`/`NO_CONFLICT`/`UNDECIDABLE_SAME_AUTHORITY`), both ad hoc record shapes, and refusals for a 3-plus-source record, an unrecognized record shape, an empty-claims record, and a non-dict input.

**Deliberately bounded.** This layer only LABELS which two source types a conflict compares; it does not re-decide `resolve_conflict()`'s verdict, does not change `escalate_conflict()`'s question-queue behavior, and adds no stage gate -- it is a pure classification function a caller may use when reporting on conflict history, nothing more.

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

## Requirement Risk IR (`dv_harness/requirement_risk_ir.py`)

Scores one requirement across six risk factors -- `complexity`, `change_frequency`, `bug_history`, `customer_impact`, `observability_difficulty`, `protocol_criticality` -- and, per the Evidence Truth Rule, never blends them into an opaque number without saying which of three honest states each factor is actually in:

- **MEASURED** -- `change_frequency` is the only mechanically-produced factor. It runs `git log --oneline -- <source_file>` under `project_root` through a read-only, degrade-never-raise `_git()` wrapper (the same contract as `trend_analysis._git()`/`change_impact._git()`, reimplemented locally rather than imported, since this module accepts `requirement_facts` as a fully generic/duck-typed parameter and never imports `requirement_contract.py` or any sibling module), then buckets the real commit count onto a documented 1-5 scale (0 commits -> 1, 1-2 -> 2, 3-5 -> 3, 6-10 -> 4, 11+ -> 5). Missing git, a timeout, a non-git-repo root, a nonexistent root, or missing `source_file`/`project_root` all degrade to `NOT_AVAILABLE` with a real reason -- never a guessed score. A real zero-commit result for a path that genuinely has no history is still `MEASURED` (score 1): that count is real evidence, not absent evidence.
- **DECLARED** -- `complexity`, `customer_impact`, `observability_difficulty`, and `protocol_criticality` have no mechanical producer anywhere in this repo. Each is read only from the caller's `requirement_facts` (dict `.get` or attribute access), validated as a real integer in `[1, 5]` (booleans explicitly rejected despite being an `int` subclass in Python), and reported `DECLARED` -- visibly distinct from a measured value. A missing or invalid declaration is `NOT_AVAILABLE`, never silently defaulted to a middle-of-scale guess.
- **NOT_AVAILABLE always** -- `bug_history` has no real producer anywhere in this repo (verified by repo-wide grep before this module was written: no defect tracker, no bug database, no incident log) and, per this task's own explicit rule, has no legitimate caller-declaration path either. `bug_history_factor()` always returns `NOT_AVAILABLE` and ignores any `bug_history` key a caller's facts might happen to carry.

`assess_requirement_risk(requirement_facts, *, source_file=None, project_root=None)` returns a `RequirementRiskProfile` with a `composite_score` computed as the mean of only the AVAILABLE factors, always reported alongside `available_factor_count`, `missing_factors`, and `coverage` (`"N/6"`) so a partial profile can never be mistaken for a complete one. `format_risk_report()` renders it for humans; a thin `main()` CLI (`python -m dv_harness.requirement_risk_ir --facts-file ... --source-file ... --project-root ...`) follows the same argparse shape as `change_cascade.py`/`golden_scenario.py`. The module reads and reports only -- it writes nothing, gates nothing, and takes no governance action.

Tested in `dv_harness_tests/test_requirement_risk_ir.py` (20 tests) against a real throwaway git repository built via subprocess (mirroring `test_trend_analysis.py`'s `rtl_repo` fixture), with real, distinct commit counts driving real bucket assignments, plus negative controls for every `NOT_AVAILABLE` degradation path (missing git inputs, non-git directory, nonexistent root, missing/invalid/out-of-range/boolean declared values) and a dedicated check that `bug_history` stays `NOT_AVAILABLE` even when a caller's facts supply one.

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

## SPEC_VPLAN_READY: Composite Readiness for the Spec-to-vPlan Pipeline Stage (2026-09-06)

This project already has two composite "is X ready" conjunctions built on the identical worst-wins discipline, and neither answers the question a caller working the SPEC-TO-VPLAN pipeline stage actually needs: `verification_intake_contract.py`'s `INTAKE_READY` is a whole-PROJECT capstone across every sub-domain intake touches, and `subsystem_maturity_gate.py`'s 9.0/9.5/10.0 levels are a whole-SUBSYSTEM maturity ladder spanning golden-flow connectivity, system smoke-proof, VIP-API provability, bind-tier cleanliness and regression evidence. Neither has any notion of "is the step that turns a parsed specification into a vPlan/requirement-contract artifact ready to drive generation, done" -- a project could be `SPEC_VPLAN_READY` while its overall `INTAKE_READY` is still `False` (a later sub-domain has not caught up), and a subsystem could clear `SPEC_VPLAN_READY` for every one of its constituent specs while sitting nowhere near 9.0 maturity (which needs conditions this gate never touches at all). A repo-wide search for `SPEC_VPLAN_READY`/`spec_vplan_ready` matched nothing executable before this: `tools/verification_flow/spec_to_vplan_quality_gate.py` and `spec_to_vplan_requirement_quality_gate.py` are per-requirement-record shape checks, not a composite verdict over a named condition set.

`dv_harness/spec_vplan_readiness_gate.py` is that composite gate, and it is deliberately a third, independent mechanism rather than an import of either neighbour -- both `verification_intake_contract.py` and `subsystem_maturity_gate.py` (along with `functional_coverage_signoff.py`, whose own Closure rollup uses the identical shape one level down) were concurrently-building batch items this module was scoped to never import. What is reused is the DISCIPLINE those modules already state as a design principle rather than a function this file could call without also importing whichever fixed condition set that module hardcodes: worst-wins, no-averaging, one unresolved condition among a hundred clean ones still blocks. `evaluate_spec_vplan_readiness()` takes a caller-assembled, caller-named list of `{"condition_name", "status", "reason"?}` records -- this module hardcodes NONE of them, since which conditions belong to "is spec-to-vplan done" (spec/doc mapping, requirement-contract completeness, vPlan/spec-delta resolution, and others) depends on whichever real per-domain producers a given project has wired.

**The fold is strictly worst-wins, two tiers deep**, over a condition-status vocabulary of `MET`/`UNMET`/`UNKNOWN`/`NOT_AVAILABLE` and a gate-verdict vocabulary of `QUALIFIED`/`NOT_QUALIFIED`/`INCOMPLETE_EVIDENCE` (both checked disjoint from `models.Status` at import time, the identical guard `subsystem_maturity_gate.py` applies to itself, reimplemented rather than imported since that module is off the import list here): any `UNMET` condition makes the whole gate `NOT_QUALIFIED` outright, regardless of how many others are `MET` and regardless of whether any other condition is `UNKNOWN`/`NOT_AVAILABLE` too -- a single unresolved requirement or vPlan gap is never diluted into a percentage or an average. Only once no condition is `UNMET` does any `UNKNOWN`/`NOT_AVAILABLE` condition make the result `INCOMPLETE_EVIDENCE` -- this task's own instruction stated in code: an unresolved-evidence condition is a third, honestly distinct outcome, never silently read as either a pass or a confirmed failure. Every condition `MET` is the only path to `QUALIFIED`. An absent or empty condition list is `INCOMPLETE_EVIDENCE` with a real reason, never a vacuous `QUALIFIED` over zero conditions measured -- the same "an empty input is UNKNOWN, never READY" rule this project's other composite folds already state. A malformed record (missing `condition_name`/`status`, an empty name, an unrecognized status, or a name repeated by an earlier record in the same list) raises `SpecVplanReadinessGateError` naming exactly what was wrong, rather than being silently dropped or resolved by picking one.

**It reads only.** No stage runs, no gate script is invoked, no build/regression/LSF job starts, and it writes no state/control/approval file of its own -- `ControlPlane.approve()`, `policy.can_signoff()`, `assert_human_approval()` and the PR-only main/master governance are untouched and unreferenced, checked against the module's own real code (not its prose, which legitimately discusses these mechanisms by name as precedent) by a tokenize-based test. A `QUALIFIED` verdict is an input to a human's decision that the spec-to-vplan stage is done, never a substitute for one, and there is deliberately no stage gate of its own.

Front door: `python -m dv_harness.spec_vplan_readiness_gate statuses|verdicts|evaluate --conditions <file> [--json]` (no `dv-harness` CLI verb -- `cli.py` and `gates.py` are on this batch's never-touch list, the same disclosed choice several very recent same-day additions in this repo have also made). Exit 0 `QUALIFIED`, 1 `NOT_QUALIFIED`, 2 `INCOMPLETE_EVIDENCE` or a usage/malformed-input error.

Proven by `dv_harness_tests/test_spec_vplan_readiness_gate.py` (33 tests): the core positive path; the headline no-averaging negative control (20 clean conditions plus one `UNMET` still reads `NOT_QUALIFIED`); `UNKNOWN` and `NOT_AVAILABLE` each independently proven to produce `INCOMPLETE_EVIDENCE`; `UNMET` proven to outrank `UNKNOWN` when both are present in one condition set; an empty/`None` condition list proven `INCOMPLETE_EVIDENCE`; five malformed-record negative controls each raising the correct named error; a real `ast.parse` of the module's own import statements proving it never imports `verification_intake_contract`/`subsystem_maturity_gate`/`functional_coverage_signoff`; and four real `python -m` subprocess invocations asserting all three exit codes plus JSON shape.

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

## VIP Example Composition: a 7-Condition Composability Gate (2026-09-06)

Composing several already-qualified VIP examples into ONE scenario -- e.g. a USB3 host example plus a USB3 device example, or a host example plus an unrelated protocol's monitor example -- had no compatibility check anywhere in this repo. `vip_capability_extraction.py` classifies individual VIP source CLASSES with a qualification tag; `env_manifest.py` records which VIP instances are configured in ONE already-generated environment; `ip_ownership_conflict.py` and `system_resource_inventory.py`'s SYS-11/SYS-12 machinery flag ownership conflicts for a single subsystem or across already-composed SoC subsystems. None of them answers the earlier, narrower question this module answers: given a caller-declared SET of individually-qualified VIP examples about to be combined into one scenario, are they actually compatible with each other -- checked against seven concrete conditions -- before any of that content is merged into a single command.txt/scenario body.

`dv_harness/example_composition.py` is that gate. Per this batch's file-safety scope it imports NOTHING from `vip_capability_extraction.py`, `ip_ownership_conflict.py`, or `system_resource_inventory` (concurrently-owned or separately-existing mechanisms this module deliberately does not duplicate) -- `examples` is a plain, alias-tolerant list of dicts, the same general shape `vip_capability_extraction.py` would produce for a qualified VIP artifact record, widened with the composition-specific facts this task names. It does not itself decide whether an example is qualified; that judgment belongs to whatever produced the record. Composing means: given examples the caller already asserts are individually usable, are they usable TOGETHER.

**Seven conditions, every one a pure structural comparison of caller-declared facts, never a semantic judgment about protocol behaviour.** (1) VIP version -- examples sharing one normalised `vip_type` must declare the same `vip_version` (scoped by package identity, never by link). (2) Role -- on one logical link, at most one example may declare a role this module recognises as ACTIVE (HOST/MASTER/INITIATOR/DRIVER/ACTIVE/ROOT_COMPLEX/RC/REQUESTER); an unrecognised role never blocks and is never assumed either way. (3) Protocol mode -- examples on one logical link must declare the identical protocol mode. (4) Agent config -- for every `agent_config` field two or more examples on one link both declare, the values must agree; a field only one side declares is never compared. (5) Sequencer ownership -- two or more examples declaring the SAME explicit sequencer/interface/bind path and both resolving to an ACTIVE driver (declared, or inferred from the fixed ACTIVE/PASSIVE role vocabulary) is a real ownership collision; an unresolved active status is reported separately and never forced into a conflict. (6)/(7) Reset/clock assumptions -- two or more examples naming the SAME reset/clock signal must agree on its declared active_level/synchronous (reset) or frequency_mhz/period_ns/edge (clock) facts.

**The one deliberate, disclosed design choice: `_link_key()`'s fallback.** Conditions 2-4 are scoped to one caller-declared logical link (`link_id`/`interface_id`/`port_id`, falling back to a declared `sequencer_path`, falling back further to one shared `UNSPECIFIED_LINK` bucket when neither is declared). That last fallback is deliberate: when an example set gives this module no way to tell two examples apart as independent ports, treating them as unrelated would be an unearned assumption of independence, so they are conservatively grouped together and a real disagreement among them is surfaced rather than hidden behind absent disambiguating evidence. A caller composing a genuine independent multi-port scenario must declare `link_id`/`port_id`/`sequencer_path` to tell the ports apart -- the same evidence this module would need to do so correctly.

**Never resolves a conflict, only names the pair.** Every conflict is reported as `status: BLOCKED` naming the exact conflicting pair (both examples' declared identities) and the specific disagreeing value(s) -- never silently merged, never averaged, and this module never picks a winner between two conflicting examples; that stays a human/caller decision, the same ARBITRATION boundary `requirement_contract.py` and `design_knowledge_correlation.py` already keep for their own conflict findings.

Malformed input is reported and excluded, never silently absorbed: a non-dict entry, an entry with no resolvable identity, and every entry sharing a duplicate identity all land in `malformed_examples` rather than participating in composition (a duplicate identity excludes ALL entries sharing it, never picking one to keep). Fewer than two valid, uniquely-identified examples reports `NOT_AVAILABLE` naming the real count; `examples` itself not being a list/tuple raises `CompositionInputError`.

**Deliberately bounded, and stated rather than implied closed.** This module builds no VIP API, no RTL content, and no scenario/command.txt body; it runs no build/regression/LSF job, and there is deliberately no `STAGE_GATES` entry -- a gate that passed on a composition nobody actually generated from would be worse than none. There is no `dv-harness` CLI verb (`cli.py`/`gates.py` are out of this batch's file-safety scope); the front door is `python -m dv_harness.example_composition compose --examples <file.json> [--json]` (exit 0 COMPOSED, 1 BLOCKED, 2 NOT_AVAILABLE).

Proven by `dv_harness_tests/test_example_composition.py` (26 tests): a clean, fully-compatible USB3 host+device pair composes with zero findings and a no-mutation proof over the input, then each of the 7 conditions is driven to a real, named-pair `BLOCKED` conflict by mutating one fact at a time off that same clean baseline, each paired with a negative control proving the check does not over-fire (different-vip_type examples never compared on version, two independent HOSTs on genuinely different declared links never conflict on role while two with no link information at all DO -- the disclosed fallback's detection power, an active driver sharing a path with a passive one is not an ownership conflict, an unresolved active status is reported but never forced into a conflict, differently-named reset signals are never compared, and clock numeric tolerance never manufactures a false conflict from float representation noise). Three malformed-input controls (non-dict entry, missing identity, duplicate identity excluding both), an insufficient-examples control, a non-sequence-input refusal, and three real CLI subprocess invocations asserting exit codes 0/1/2 round out the suite. Ran `python -m pytest dv_harness_tests/test_example_composition.py -q` -> `26 passed`.

## Per-Pattern Marginal Coverage Contribution: Attribution the Aggregate Curve Cannot Give (2026-09-06)

`loop_convergence.py`'s own docstring is explicit about its own boundary: its coverage series is `trend_analysis.daily_rollup()`'s bins-weighted, PROJECT-WIDE `coverage_percent` curve -- one number per day, aggregated across every pattern that ran that day -- and that module "never attributes movement to one pattern". It can tell you the project is CONVERGING, PLATEAU'd, or OSCILLATING; it cannot tell you which pattern moved the needle, by how much, at what runtime/failure cost. `dv_harness/pattern_coverage_contribution.py` answers that different, narrower question: for ONE named pattern, what new coverage bins (and, of those, which new cross-coverage bins are independently meaningful rather than fully explained by their own already-covered single-axis bins) did its own run(s) contribute, and at what real runtime/failure cost -- never an aggregate curve, always attributed to the one pattern named.

**The real gap, found by grepping `evidence_db.py`'s schema before writing a line of code, per this batch's own instruction.** `coverage_samples` (`insert_coverage_sample()`) is this project's one real coverage-sample store, and its real columns are `(id, category_name, percent, bins_total, bins_hit, sample_timestamp, source, ingested_at)` -- there is **no `pattern` column**. In production, `dashboard._ingest_coverage_summary_to_evidence_db()` passes the `summary.json` PATH as `source`, never a pattern name. `evidence_db.py`'s OTHER real per-pattern table, `jobs`, DOES carry a real `pattern` column plus `runtime_seconds`/`uvm_error_count`/`uvm_fatal_count`/`assertion_failure`/`simulator_crash` -- real, already-attributable evidence needing no new linkage. So the honest state of this project's evidence store is: runtime and failure evidence per pattern already exists; coverage-BIN evidence exists only as an un-attributed, project-wide checkpoint sequence. This module reuses `coverage_samples`/`jobs` EXACTLY as recorded (no new column, no write path -- every read goes through `EvidenceStore(db_path, read_only=True).query()` with an explicit column list zipped back into named dicts, the same convention `protocol_compliance_aggregation.py`'s `load_normalized_evidence_rows()` already established) and asks the ONE additional real fact the schema cannot supply on its own: which checkpoint (`source` value) belongs to which pattern's run. That fact arrives as a required, explicit, caller-declared `sample_attribution` (`[{"source", "pattern"}, ...]`) -- the same "accept an explicit caller-declared fact the real evidence store cannot supply, rather than invent one" discipline `ip_ownership_conflict.py`'s `legacy_bfm_declarations` and `existing_command_reuse_score.py`'s `existing_commands` already use. A pattern with no attributed checkpoint, and no `jobs` rows, has recorded NOTHING this project's evidence store can attribute to it, and reports `NOT_AVAILABLE` for its contribution -- never an estimated or zero delta.

**Mechanics.** `group_into_checkpoints()` groups real `coverage_samples` rows by their own `source` field into chronologically-ordered checkpoints (ordered by the real DuckDB `id` sequence -- never trusted by wall-clock `sample_timestamp`/`ingested_at` resolution). `compute_pattern_coverage_contribution(db_path, pattern, sample_attribution, cross_definitions=None)` walks checkpoints in order, and for each one attributed to `pattern` diffs every category's `bins_hit` against the state immediately prior (baseline 0 for a category never seen before that point), summing `new_bins_hit` across all of the pattern's own checkpoints. A negative delta (bins un-hit between checkpoints, however unusual) is never counted toward `new_bins_hit` (floored at 0) but is still honestly surfaced in `regressed_categories` -- never silently hidden. `coverage_delta_percent` is a bins-weighted percent movement over only the categories the pattern actually touched. Runtime/failures come straight from real `jobs` rows filtered by `pattern`. `cost` is ALWAYS reported `NOT_AVAILABLE` with a real cited reason: a repo-wide check before writing this module found no per-job compute/license-usage cost producer anywhere in this codebase -- `loop_budget.py`'s own CLAUDE.md section states plainly that "max_compute / max_license_usage / max_token_cost ... have no producer in this harness at all" -- so inventing one here would be exactly the fabrication the Evidence Truth Rule forbids. Overall status is `MEASURED` only when both the coverage side and the runtime/failure side were measured; `PARTIALLY_MEASURED` when only one was; `NOT_AVAILABLE` when neither was -- three honestly distinct states, never averaged or collapsed.

**"Meaningful crosses only", built independently rather than importing a claimed file.** `coverage_analysis.py` already has a private `_cross_axes()`/`_cross_axes_all_covered()` pair solving almost exactly this same question (used there to classify a `CROSS_COVERAGE_ONLY_UNCOVERED` coverage hole) -- but `coverage_analysis.py` was one of this batch's own claimed/never-import files, so `classify_cross_coverage_meaningfulness()` re-derives the identical, small, generic logic directly over plain `{"percent","bins_total","bins_hit"}` category dicts (the same shape `coverage_samples` rows already carry) rather than importing a claimed module or leaving the helper unbuilt. It flags a caller-declared cross-coverage bin (`{"cross_name", "axes": [axis1, axis2, ...]}`) `FULLY_EXPLAINED_BY_AXES` (skip-worthy) ONLY when EVERY declared axis is a real, matched, `>= 100%`-covered category in the supplied snapshot; a missing or unmeasurable axis reads `UNKNOWN_AXIS_COVERAGE` and is NEVER treated as fully-explained -- absence of proof that the axes explain the cross is never read as proof they do, so an unprovable cross bin's new hits still count toward `new_crosses_hit`. Meaningfulness is evaluated against the coverage state as it stood immediately BEFORE the pattern's own contribution began, not the final project-wide state -- "already fully explained" means already, prior to this pattern's own run.

**Status vocabulary is asserted disjoint from `dv_harness.models.Status` at import time** (`MEASURED`/`PARTIALLY_MEASURED`/`NOT_AVAILABLE`, `CROSS_MEANINGFUL`/`CROSS_FULLY_EXPLAINED`/`CROSS_UNKNOWN`) -- the same guard `capability_evolution.py`/`benchmark_dataset.py`/`subsystem_maturity_gate.py` already run on their own vocabularies (`PARTIAL` was caught colliding with `Status.PARTIAL` during this module's own test run and renamed to `PARTIALLY_MEASURED` before landing).

**Deliberately bounded, and stated rather than implied closed.** (1) It never writes to `evidence_db.py` -- no `insert_*` method is ever called from this module, and it constructs `EvidenceStore` only in `read_only=True` mode. (2) It arbitrates nothing and runs no gate; there is deliberately no stage gate. (3) `cost` can never resolve to a real measured value in this codebase today -- disclosed rather than silently omitted. (4) It is REACHED, not WIRED: there is a `python -m dv_harness.pattern_coverage_contribution` front door but no `dv-harness` CLI verb, no `run_stage()`/`advance()` call site, and no graph node.

Proven by `dv_harness_tests/test_pattern_coverage_contribution.py` (17 tests), every coverage-sample and job row populated exclusively through `evidence_db.py`'s own real `insert_coverage_sample()`/`insert_job_state()` methods -- never a hand-written store row. The core positive path drives two patterns' real checkpoints (one improving a cross bin whose axes are NOT both yet fully covered, proving `INDEPENDENTLY_MEANINGFUL` rather than a fabricated skip) through real job runtime/failure evidence. Negative controls: no attribution and no jobs -> `NOT_AVAILABLE` (never a fabricated zero, asserted by checking the key is simply absent); coverage-only measured -> `PARTIALLY_MEASURED`; jobs-only measured -> `PARTIALLY_MEASURED`; a malformed attribution entry and an ambiguous same-source-two-patterns attribution both raise `PatternCoverageContributionError`; a wholly absent evidence.duckdb reports `NOT_AVAILABLE` without crashing; a real coverage regression between checkpoints is reported honestly in `regressed_categories` and never counted as new; a cross bin whose axis category cannot be found at all reads `UNKNOWN_AXIS_COVERAGE` and still counts toward `new_crosses_hit` (never silently skipped); and multiple checkpoints attributed to the same pattern are correctly summed. Both real CLI exit-code paths (`MEASURED` -> 0, `NOT_AVAILABLE` -> 2) are driven as real subprocesses.

## Coverage-Closure Action Utility: Rank Actions, Gate Correctness/Risk Before Cost (2026-09-06)

Plenty of per-hole coverage ANALYSIS exists in this repo (`coverage_analysis.classify_coverage_hole()`'s four root causes, `classify_coverage_hole_taxonomy()`'s twelve structural categories) and plenty of per-project READINESS rollups (`generation_readiness.py`, `golden_flow_readiness.py`, `subsystem_practicality_score.py`), but nothing RANKED a set of proposed coverage-closure remediation actions against each other. A coverage-closure effort routinely has more candidate actions (write a directed test, relax an over-constrained sequence, add a waiver, escalate as unreachable) than budget to pursue at once, and nothing ordered that list by expected value. A repo-wide grep for `coverage_closure_action`/`expected_coverage_gain` before this module matched nothing executable.

`dv_harness/coverage_closure_action_utility.py` ranks a duck-typed list of candidate actions by `utility = expected_coverage_gain x requirement_priority x risk_coverage / cost`. `evidence_db.py`'s real `coverage_samples` table (read, never imported, before designing this) is keyed by `category_name`/`percent`/`bins_total`/`bins_hit` -- a coverage tool's own per-category rollup, with no candidate-action, requirement-priority, risk-coverage, or cost concept at all. There is no mechanical producer anywhere in this repo for any of the four factors this formula needs, so -- exactly as `requirement_risk_ir.py` established for its own four caller-declared risk factors -- every factor here is accepted only as an explicit caller declaration and reported with status `DECLARED`, visibly distinct from a `MEASURED` value, never re-derived and never defaulted to a guessed number when absent or invalid (that reports `NOT_AVAILABLE` instead).

**The document's own explicit rule is enforced as code, not merely described: "a cheap-but-wrong action must never outrank a correct one regardless of cost."** Two caller-declared judgments -- `correctness_status` (CONFIRMED_CORRECT/FLAGGED_INCORRECT/UNVERIFIED) and `risk_status` (ACCEPTABLE_RISK/HIGH_RISK/UNVERIFIED), each independent of the `risk_coverage` utility factor (which measures how much risk surface an action addresses, a benefit; `risk_status` asks whether taking the action is itself dangerous, a gate) -- are resolved and applied by `_gate_candidates()` **before** any utility factor, including cost, is ever read for that candidate. A `FLAGGED_INCORRECT`/`HIGH_RISK` action is moved to a separate `excluded` bucket carrying `utility_score=None` and named exclusion reasons -- it is never scored, never ranked with a fabricated low score, and never merely penalized; its declared factors are still reported alongside for audit transparency. Only once gating has removed every flagged action does `_compute_utility()` run for the survivors, and only then does a genuine utility tie among survivors get broken by cost (ascending, cheaper first) and finally by `action_id` for full determinism -- an ordering this module's own call sequence makes structurally impossible to reverse (cost is never read before the gate has decided eligibility). An action with neither flag declared defaults to `UNVERIFIED` on both axes and is NOT excluded -- exclusion is reserved for an explicit flag, never inferred from silence, per the Evidence Truth Rule's ban on treating absence as a finding. An action missing a required utility factor, or declaring an invalid one (zero, negative, boolean, non-numeric, NaN/inf), or declaring an unrecognized gate-status string, is reported `UNRANKABLE` in a third bucket rather than given a fabricated default.

Front door: `python -m dv_harness.coverage_closure_action_utility --candidates-file <file.json> [--json]` (exit 0 all ranked/excluded, 1 at least one candidate is unrankable). No `dv-harness` CLI verb was added and `gates.py`/`cli.py`/`CLAUDE.md` were not touched, per this task's own file-safety scope; this module imports nothing from `dv_harness` itself, including no file from the concurrently-running batch, accepting a candidate action only as a generic duck-typed mapping/object.

Proven by `dv_harness_tests/test_coverage_closure_action_utility.py` (24 tests): the core positive path ranking three candidates by the exact formula; the two headline negative controls proving a cheap/enormous-utility action flagged `FLAGGED_INCORRECT`/`HIGH_RISK` is excluded entirely and never outranks a correct/safe modest-utility one (a case constructed so the wrong action's utility, if computed, would rank #1); a both-flags-together case; cost breaking a genuine utility tie only among gate-cleared candidates, plus a deterministic `action_id` final tie-break; six invalid-factor-value negative controls (0, negative, bool, non-numeric, NaN, inf); a missing-factor negative control; two invalid-gate-string negative controls (proven `UNRANKABLE`, never silently defaulted or silently accepted); an empty-candidate-list refusal (never a vacuous ranking); duck-typed dict vs. attribute-object acceptance; `action_id`/`id`/positional-placeholder fallback; rationale pass-through; the report renderer naming all three buckets; and two real `python -m dv_harness.coverage_closure_action_utility` subprocess CLI runs asserting exit codes 0 and 1. `python -m pytest dv_harness_tests/test_coverage_closure_action_utility.py -q` -> `24 passed`.
</content>


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

## Subsystem Adapter IR: a Fixed 8-Operation Facade Over Real Task/Sequence Names (2026-09-06)

Every subsystem-mode verification environment this project builds already carries its own real, generated task/sequence names -- an `init_seq.py`-style directed test step, a `branch_b*`-driven VIP sequence, a hand-authored `command.txt` task, each following that particular subsystem's own naming convention. Nothing anywhere spoke a FIXED, cross-subsystem vocabulary of logical operations against those real names: a caller wanting to "start this subsystem" or "wait until it is ready" had no single place to ask that question without first learning the specific subsystem's own naming scheme. Building a second task/sequence catalog from scratch, or guessing a plausible task name for an operation nobody actually declared, would be exactly the "invent a stub implementation" the Evidence Truth Rule forbids.

`dv_harness/subsystem_adapter_ir.py` is the facade, and only the facade. `LOGICAL_OPERATIONS` is a fixed, import-time-pinned 8-value tuple (`configure`/`start`/`stop`/`reset`/`wait_ready`/`execute`/`monitor`/`get_status`) -- `assert_logical_operations_fixed()` runs at import and fails loudly if a future edit silently widens, narrows, reorders-with-duplicates, or otherwise drifts the vocabulary. `build_subsystem_adapter_ir(mapping_entries, subsystem_name=None)` accepts a duck-typed list of `{operation, existing_task_or_sequence_name}` records -- plain dicts or any object exposing `.get()`, never a dict subclass requirement -- and resolves each of the 8 fixed operations to exactly one `OperationResolution`:

- **RESOLVED** -- the caller supplied a real, non-empty (after whitespace-trimming) task/sequence name for this logical operation. The name is carried through verbatim, trimmed only; this module never rewrites, normalizes, or "corrects" it.
- **UNSUPPORTED_OPERATION** -- no real mapped task/sequence exists for this operation, whether because the caller's mapping never mentioned it at all, or because it was mentioned with an empty/whitespace-only name (a legitimate explicit "we have nothing for this" declaration). Both paths report the identical honest status and reason, and neither ever synthesizes a fabricated task/sequence name to fill the gap -- the module's one hard rule, restated from its own governing instruction: never invent a stub for a missing mapping.

An operation named in `mapping_entries` that falls OUTSIDE the fixed eight-operation vocabulary is never silently dropped: it is collected into `unrecognized_mappings` on the resulting `SubsystemAdapterIR`, carrying its own real reason, and it never resolves (or leaves unsupported) any of the eight real logical operations -- a caller reading the IR can always see and correct a mis-named mapping rather than have it silently vanish.

**Malformed or ambiguous input is a hard, named error, never a silent repair.** A non-sequence `mapping_entries`, an entry that is not mapping-shaped at all, an entry with a missing or blank `operation`, an entry whose `existing_task_or_sequence_name` key is entirely ABSENT (deliberately distinct from being present as an empty string, which is a legitimate "explicitly unmapped" declaration), or the same operation mapped more than once across one caller-supplied list, each raise `SubsystemAdapterIRError` with a distinct `code`/`detail` -- mirroring `task_return_model.TaskReturnModelError`'s "never silently repaired" discipline for the identical reason: silently resolving a duplicate or malformed declaration on the caller's behalf would hide a real authoring defect from the person who needs to see it. `resolve()`/`is_supported()` likewise reject a request for an operation outside the fixed vocabulary rather than reporting a fabricated `UNSUPPORTED_OPERATION` for a question this module was never asked to answer.

**Deliberately bounded, and stated rather than implied closed.** This module imports nothing else from `dv_harness` -- verified directly against its own import statements -- so it stays usable regardless of which concurrently-built module eventually owns producing a real mapping for a given subsystem; every mapping is accepted as a generic, duck-typed record rather than a specific producer's typed output. It authors no task/sequence body and validates nothing about whether a resolved name is itself syntactically or semantically correct against the underlying environment -- that is a downstream generator's job. It runs no build, no simulation, no LSF submission, mints no approval, and holds no stage gate of its own; it only resolves a caller-supplied mapping against the fixed 8-operation vocabulary and reports, honestly, what that mapping does and does not cover.

Proven by `dv_harness_tests/test_subsystem_adapter_ir.py` (20 tests): fixed-vocabulary sanity plus two mutation-style negative controls proving the import-time drift/duplicate assertion has real detection power; the full-mapping positive path (all 8 operations resolved, names trimmed-but-never-otherwise-rewritten); an empty mapping list (all 8 honestly unsupported); the never-mentioned-vs-explicitly-empty-name distinction (both `UNSUPPORTED_OPERATION`, with distinguishable `reason` text); an unrecognized operation name reported without ever bleeding into a real operation's resolution; `resolve()`/`is_supported()` rejecting an out-of-vocabulary request; six negative controls for malformed/ambiguous input; and a genuinely duck-typed (non-dict, `.get()`-only) mapping-record object proving the input contract is real duck-typing rather than dict-only support in disguise. Run: `python -m pytest dv_harness_tests/test_subsystem_adapter_ir.py -q` -> `20 passed`.

## System Failure Taxonomy: SYSTEM-INTEGRATION Failures, Boundary Localization, Coverage-Hole Scope (2026-09-06)

Three real, closely-related classification mechanisms, one module, because they answer questions at the SAME grain -- the SYSTEM/multi-subsystem-composition level, not the per-command-dispatch level `command_error_taxonomy.py` already owns (eleven categories, one per failed command/task call) and not the per-stage-retry level `loop_budget.FailureType` already owns (ten categories feeding a retry-vs-stop decision). Nothing in this repo classified a failure at the grain a COMPOSED multi-subsystem environment actually breaks at -- a merge collision during system build, a cross-subsystem address-map disagreement, two active VIP agents driving one port, a scoreboard mismatch that only shows up once two subsystems' transactions are compared together. `dv_harness/system_failure_taxonomy.py` is that missing coarser layer.

**(a) A 14-value SYSTEM-INTEGRATION failure taxonomy** (`SUBSYSTEM_FAILURE`, `INTEGRATION_FAILURE`, `ROUTING_FAILURE`, `RESOURCE_CONTENTION_FAILURE`, `ADDRESS_MAP_FAILURE`, `CLOCK_RESET_FAILURE`, `COMMAND_COMPATIBILITY_FAILURE`, `BUILD_COMPOSITION_FAILURE`, `SCOREBOARD_COMPOSITION_FAILURE`, `VIP_DEDUP_FAILURE`, `ERROR_PROPAGATION_FAILURE`, `TIMING_FAILURE`, `CONFIGURATION_FAILURE`, `RECOVERY_FAILURE`) plus the honest `UNCLASSIFIED` fallback. `classify_system_integration_failure(text)` is a pure, regex-rule-based classifier over whatever real failure text a caller already has (a `system_build_proof`-shaped merge report line, a cross-subsystem gate's own rejection text, a composed environment's sim.log excerpt) -- it reads no file and runs no subprocess itself, matching `command_error_taxonomy.py`'s own house style (a fixed `CLASSIFICATION_ORDER`, most structurally specific rule first, each rule citing the exact matched evidence substring and 1-indexed line). An unmatched text is `UNCLASSIFIED`, never forced into one of the fourteen named categories. `TIMING_FAILURE` classifies already-REPORTED timing/race-relationship violation TEXT (a setup/hold violation citation, a race condition, a glitch) -- it measures nothing and runs no timing analysis of its own, so it is not the Performance Verification this entire gap-closure batch deferred; it is a text classifier over evidence some other, already-real tool produced.

**Deliberately DIFFERENT, coarser scope than its two nearest neighbours, stated explicitly rather than left to be discovered.** `command_error_taxonomy.py`'s eleven categories answer "why did THIS ONE command/task dispatch fail". `loop_budget.FailureType`'s ten categories answer "why did THIS STAGE'S RETRY exhaust". This module answers "what KIND of SYSTEM/multi-subsystem-composition failure is this" -- a different, wider grain neither of those two is built to express. Because both of those modules were claimed by a concurrently-running batch of this project's own gap-closure work, this module imports neither: the non-collision is instead asserted against a literal, hand-transcribed copy of each module's own published category vocabulary (`assert_disjoint_from_command_error_taxonomy()` / `assert_disjoint_from_loop_budget_failure_type()`, both run at import time), the same "state the distinction in code, do not silently assume it" discipline several other pairs of near-adjacent vocabularies in this project already apply to themselves. A third guard, `assert_disjoint_from_verification_verdict_vocabulary()`, imports `dv_harness.models.Status` (a small, stable, unclaimed enum, safe to import) to prove this module's full vocabulary -- both taxonomies plus the boundary-localization status words -- never collides with a real stage verdict.

**(b) Root-cause BOUNDARY localization, never a claimed root cause.** `localize_failure_boundary(subsystem_io_map, connections=None)` takes a caller-supplied, fully duck-typed per-subsystem input/output correctness map (each subsystem declaring its own input and output as `CORRECT`/`INCORRECT`/`UNKNOWN`, via either a string-shaped or a bool-shaped record) and names the NARROWEST subsystem boundary the evidence actually proves -- exactly one subsystem whose input is confirmed `CORRECT` and whose output is confirmed `INCORRECT` is the only case that narrows (`status: "NARROWED"`, that subsystem named as `boundary`). Zero such subsystems, more than one, or a real contradiction across a caller-declared direct connection (an upstream `CORRECT` output paired with a downstream `INCORRECT` input on the same wire, or the reverse) all report `status: "UNDETERMINED"` with `boundary: None` and the real candidate set or contradiction cited in `reason` -- never a guessed single subsystem. This is the module's one hard rule: it never claims a specific root cause the input data does not prove, per this batch's own Evidence Truth Rule (rule 8: a Critical UNKNOWN must never silently become a resolved finding).

**(c) A 6-value system coverage-hole taxonomy** (`SUBSYSTEM_GAP`, `INTEGRATION_GAP`, `RESOURCE_GAP`, `SCENARIO_GAP`, `ERROR_PATH_GAP`, `COVERAGE_MODEL_GAP`) plus the honest `UNCLASSIFIED_COVERAGE_HOLE` fallback, via `classify_system_coverage_hole(hole)` over a caller-declared, duck-typed hole record (`coverage_model_missing`, `involves_shared_resource`, `involves_error_path`, `scope`/`subsystem_ids`/`subsystem_id`, `scenario_category_missing`). **Deliberately a different, coarser-grained taxonomy from `coverage_analysis.classify_coverage_hole()`'s four per-BIN root causes** (`MISSING_TEST`/`INSUFFICIENT_CONSTRAINT`/`UNREACHABLE_STIMULUS`/`INSUFFICIENT_SEED_ATTEMPTS`, plus this project's own twelve-value structural extension) -- that mechanism answers "why is ONE coverage bin unhit", read off a real coverage-tool summary and a real seed-attempt count; this module answers "what KIND of system-level gap does a coverage hole represent" (scoped to one subsystem, spanning an integration path, a shared-resource scenario, an error path, a whole missing scenario category, or a coverage MODEL that was never even defined). The six category names share no token with `coverage_analysis`'s vocabulary, and `coverage_analysis.py` is on this batch's claimed-file list, so it is never imported here either -- the two mechanisms compose at a caller rather than one subsuming the other.

**What this module does not do.** It classifies and localizes; it never decides which subsystem to fix, never arbitrates a resource-ownership conflict (that stays `system_resource_inventory.py`'s SYS-11/SYS-12 territory, deliberately not imported here since it is not named by this task), never retries anything, never spends a budget, never decides PASS/FAIL for a stage, and touches no human-approval gate. It performs no file I/O and no subprocess call anywhere in the module -- every input across all three mechanisms is a plain, generic/duck-typed parameter.

Proven by `dv_harness_tests/test_system_failure_taxonomy.py` (58 tests): vocabulary shape/disjointness including a mutation test proving the disjoint guards have real detection power against a real `command_error_taxonomy`/`loop_budget` category name; one positive-match test per each of the fourteen failure categories plus honest-fallback and rejection negative controls (empty text, unmatched text, `None`/non-string input) plus two priority-ordering tests proving `CLASSIFICATION_ORDER` is actually honoured when two categories' markers co-occur in one text; boundary localization's single-candidate narrowing (both string- and bool-shaped input), zero-candidate cases (with and without a blocking `UNKNOWN`), a multiple-independent-candidate `UNDETERMINED`, a real cross-connection contradiction, an unresolvable-connection-ignored-not-assumed case, and six malformed-input negative controls; and one positive test per each of the six coverage-hole categories plus two priority-conflict tests and malformed-input negative controls. Run: `python -m pytest dv_harness_tests/test_system_failure_taxonomy.py -q` -> `58 passed`.

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

### pattern_fragment_ir.py -- reusable pattern-fragment extraction for later system-level composition

`dv_harness/pattern_fragment_ir.py` converts a reusable PORTION of an existing subsystem pattern -- never a whole scenario -- into a `PatternFragmentIR`: a small, composable record carrying `preconditions`, `postconditions`, `resources_used`, and `produced_events`/`consumed_events`, so a later system-level composition step has something concrete to reason about instead of re-reading raw pattern text.

**Explicitly distinct from two real, easy-to-confuse modules.** `pattern_ir_assembly.py` assembles the FULL `PatternIR` for ONE scenario -- its `global`/`dut`/`fw_policy`/`vip`/`check` five-layer command lists, built from a whole ScenarioIR-shaped item list; it answers "what does this entire scenario's pattern look like, laid out into its five fixed layers". `example_composition.py` composes multiple already-qualified WHOLE VIP EXAMPLES (a host example plus a device example, say) into one scenario, gated by a 7-condition example-level compatibility check (VIP version, role, protocol mode, agent config, sequencer ownership, reset/clock assumptions). `pattern_fragment_ir.py` answers a narrower, different question than either: given ONE existing pattern's command list and a caller-declared PORTION of it -- an index range, or a marker-delimited slice, never the whole thing by default -- extract that portion as a self-describing fragment carrying what resources it touches, what events it needs already asserted before it runs, and what it leaves behind. It never assembles a scenario's five PatternIR layers and never checks VIP-example-level compatibility. Per this batch's file-safety scope it imports nothing from `pattern_ir_assembly.py`, `example_composition.py`, or any other claimed batch file; `fragment_source` is accepted as a plain duck-typed object via a locally re-derived tolerant-alias field-access helper, not an imported one.

**Selection.** `extract_pattern_fragment(fragment_source, *, fragment_range=None, start_marker=None, end_marker=None, declared_preconditions=None, declared_postconditions=None, fragment_id=None)` resolves the fragment's command slice one of three ways: an explicit `(start, end)` half-open index pair (`SELECTION_EXPLICIT_RANGE`), a `start_marker`/`end_marker` inclusive text-matched pair (`SELECTION_MARKER_RANGE`), or, when neither is supplied, the entire source command list -- honestly flagged `SELECTION_WHOLE_SOURCE_USED_NO_RANGE_DECLARED` with `covers_entire_source=True` rather than silently pretending a portion was declared. An unrecognisable `fragment_source` (no list-shaped commands field under any known alias), an invalid or out-of-range `fragment_range`, an incomplete marker pair, or a marker that is never found each raise a typed `PatternFragmentIrError` carrying a specific reason code (`SOURCE_COMMANDS_NOT_LIST`, `INVALID_FRAGMENT_RANGE`, `MARKER_PAIR_INCOMPLETE`, `START_MARKER_NOT_FOUND`, `END_MARKER_NOT_FOUND`, `EMPTY_FRAGMENT_SELECTION`) -- never a silent fallback to selecting nothing or everything.

**Precondition/postcondition derivation (Evidence Truth Rule applied).** Every fact reported is read directly off the fragment's own command entries via aliased duck-typed fields (`resource`/`resources`/`uses_resource`/`driver`/`agent`; `produces_event`/`produced_event`/`emits_event`/`emits`/`produces`; `consumes_event`/`required_event`/`requires_event`/`waits_for_event`/`consumes`). Given the fragment's own produced-event and consumed-event sets, a consumed event NOT also produced within the same fragment becomes a derived precondition (`DERIVED_UNRESOLVED_CONSUMED_EVENT`) -- something the fragment assumes true on entry that it alone cannot supply; a produced event NOT also consumed within the same fragment becomes a derived postcondition (`DERIVED_UNCONSUMED_PRODUCED_EVENT`) -- something it leaves behind for whatever composes with it later. This is a plain set-difference over the fragment's own declared events, assuming no internal ordering guarantee beyond "declared inside this fragment" (consistent with a fragment being reusable, not a fully sequenced scenario) -- it never invents an event no command actually declared. Callers may additionally pass `declared_preconditions`/`declared_postconditions` (plain strings or small dicts) for facts a human or upstream tool already knows are true but no event field mechanically proves; these are kept tagged `DECLARED`, distinct from and never deduplicated against the `DERIVED_*` entries, since a declared fact and a mechanically-derived one naming the same event remain two different pieces of evidence.

**Absence-of-evidence is a distinct, honest status, never a silently-defaulted empty result.** `resource_evidence_status` and `event_evidence_status` are each `EVIDENCE_DERIVED` when at least one command in the fragment declared that kind of field, or `EVIDENCE_NOT_AVAILABLE` when none did -- kept separate from a legitimately-computed empty `resources_used`/`produced_events`/`consumed_events` list, so "nothing was declared" and "something was declared and none of it applies here" are never collapsed into one indistinguishable outcome. A command with no `text` field at all is collected into `unclassified_commands` and downgrades the fragment's overall `status` from `COMPLETE` to `PARTIAL_TEXT_EVIDENCE`, never silently dropped.

**Composition-facing structural chain check.** `check_fragment_chain_readiness(fragments, *, order=None)` takes an ordered list of `PatternFragmentIR`-shaped fragments -- a caller's declared composition order for a candidate system-level pattern -- and reports, per fragment, whether each of its `DERIVED_UNRESOLVED_CONSUMED_EVENT` preconditions is `COVERED` (an earlier fragment in that order produced or postconditioned the same event) or `UNCOVERED`, plus a per-fragment `chain_status` of `NO_PRECONDITIONS` / `ALL_COVERED` / `HAS_UNCOVERED_PRECONDITIONS`. An explicit `order` argument naming a different set of fragment ids than `fragments` actually holds raises `PatternFragmentIrError("ORDER_MISMATCH", ...)` rather than silently reordering or dropping a fragment; an empty `fragments` list raises `PatternFragmentIrError("EMPTY_FRAGMENT_LIST", ...)`. This is a purely structural event-graph check over caller-declared event names -- it never asserts, and must never be read as asserting, that the resulting composed multi-fragment pattern is behaviourally correct; it only reports whether the produced/consumed event graph is self-consistent in the declared order, reporting `UNCOVERED` rather than guessing a precondition is satisfied when no earlier fragment actually supplies it.

**Tests.** `dv_harness_tests/test_pattern_fragment_ir.py` (16 tests, all passing): the core positive path (explicit-range extraction with correctly derived resources/events/preconditions/postconditions off a real 4-command USB3 port-enumeration-shaped pattern fixture), declared-condition merging alongside derived ones, marker-based selection producing the same result as the equivalent explicit range, the whole-source-used honest flag, the NOT_AVAILABLE-vs-computed-empty distinction for a fragment with resources but no event fields, the unclassified-command status downgrade, six negative controls (non-list commands field, start>=end range, out-of-bounds range, incomplete marker pair, start marker not found, end marker not found) each asserting the specific `PatternFragmentIrError` reason code, and four `check_fragment_chain_readiness` tests (all-covered in correct declared order, uncovered when the producing fragment is omitted, empty-fragment-list error, order-mismatch error).

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

## AMBA Functional Coverage IR: Connectivity/Memory-Map/Routing/Ordering Coverpoints, 7-Value Reachability, Meaningful Crosses Only (2026-09-06)

Nothing in this repo's existing, extensive AMBA family (`amba_fabric_discovery.py`, `amba_port_registry.py`, `amba_fabric_analysis.py`, `amba_transaction_ir.py`, `amba_route_transform_predictor.py`) turned their real discovery/analysis facts into a functional-coverage IR: a set of coverpoint bins driven by connectivity legality, memory-map ownership, routing/transform paths, and ordering scenarios, each carrying an honest reachability classification rather than a binary covered/uncovered flag. `dv_harness/amba_functional_coverage_ir.py` is that IR, and it is deliberately standalone: per this batch's file-safety scope it imports neither `connectivity.py` nor `amba_master_slave_constraint_ir.py` (a separate task in the same batch owns the latter) and no other new module from this batch -- connectivity-legal-edge facts, address-region facts, route facts and ordering facts are all accepted as generic, duck-typed dict lists, the same "accept an explicit caller-declared fact rather than invent one" discipline `ip_ownership_conflict.py`'s `legacy_bfm_declarations` and `existing_command_reuse_score.py`'s `existing_commands` already established for a fact their own real evidence store cannot supply on its own.

**A 7-value reachability classification, never collapsed to binary.** `classify_bin_reachability(fact)` derives one of `COVERED_OBSERVED` / `REACHABLE_NOT_YET_HIT` / `PARTIALLY_REACHABLE_CONDITIONAL` / `UNREACHABLE_NO_LEGAL_PATH` / `UNREACHABLE_STRUCTURALLY_EXCLUDED` / `REACHABILITY_CONTRADICTED` / `REACHABILITY_UNKNOWN_INSUFFICIENT_EVIDENCE` from real evidence fields on the caller's fact dict (`observed_hit`, `legal`, `structurally_excluded`, `conditional`, `contradicting_evidence`) -- the AMBA-specific instance of the same discipline `coverage_analysis.classify_coverage_hole()`'s four root causes and this same session's `pattern_coverage_contribution.classify_cross_coverage_meaningfulness()` already apply elsewhere: never let an absence of proof read as a confirmed negative, and never let two different kinds of "not covered" collapse into one word. A real observed hit always wins over every other field. A `structurally_excluded` fact asserted alongside an affirmatively-`legal` connectivity fact is DERIVED as `REACHABILITY_CONTRADICTED` even when the caller never flagged the disagreement explicitly -- a real, checked disagreement between two evidence sources, not a guessed one.

**Four coverpoint builders**, each a thin, duck-typed reduction of a category of real caller-supplied facts into coverpoint bins: `build_connectivity_coverpoints(legal_edges)` (one bin per master-slave/source-dest pair), `build_memory_map_coverpoints(address_regions)` (one bin per owner/region, optionally crossed with an accessing master), `build_routing_coverpoints(route_facts)` (one bin per source-dest route, optionally naming its hop sequence), `build_ordering_coverpoints(ordering_facts)` (one bin per named ordering scenario -- outstanding-transaction-depth buckets, out-of-order-completion scenarios -- optionally scoped to a real master/ID). None of the four derives connectivity legality, address-map ownership, routing behaviour, or ordering semantics itself; each accepts a real, caller-supplied fact per bin and classifies its reachability through the shared `classify_bin_reachability()`.

**"Meaningful crosses only" is reimplemented independently, not imported**, per this task's own explicit instruction: `classify_cross_coverage_meaningfulness()` in `amba_functional_coverage_ir.py` is a fresh implementation of the identical small idea `pattern_coverage_contribution.py`'s own function of the same name already solves for its domain -- both answer "are this cross's two axes already fully explained by their own single-axis coverage" from the same `{"bins_total","bins_hit"}` category-snapshot shape, independently, by design for this batch. `evaluate_cross()` wires this into bin-building: a cross whose two declared axes are BOTH already 100% `COVERED_OBSERVED` is reported `FULLY_EXPLAINED_BY_AXES` and SKIPPED -- zero per-combination cross bins are built at all, because the point of "meaningful crosses only" is to not even track a cross whose information the two single-axis bin sets already fully carry. A cross missing evidence for either axis is `UNKNOWN_AXIS_COVERAGE`, never silently read as either meaningful or fully explained.

`AMBAFunctionalCoverageIR.build(legal_edges=, address_regions=, route_facts=, ordering_facts=, cross_requests=)` assembles all four coverpoint categories plus zero or more cross evaluations (each cross request may name its two axes' snapshots directly, or reference one of this same call's own just-built categories via `axis_a_category`/`axis_b_category`, through the new `axis_snapshot_from_bins()` reducer -- never a stale, separately-passed axis set) into one `all_bins()`/`reachability_summary()`/`to_dict()`-capable IR. `dv-harness` was not touched (per this task's own file-safety scope); the ad hoc front door is `python -m dv_harness.amba_functional_coverage_ir build --facts <file.json> [--json]`.

**Deliberately bounded, and stated rather than implied closed.** (1) It decides nothing beyond classification and cross-selection: it writes nothing to any evidence store, mints no memory/blackboard/approval record, runs no build/regression/LSF submission, and there is deliberately no stage gate -- a gate that passed on a coverage IR nobody reviewed would be worse than none. (2) It never derives connectivity legality, address-map ownership, routing/transform behaviour, or ordering semantics itself -- every one of those is a real fact a caller's own pipeline (a real connectivity pass, a real address-map cross-check, `amba_route_transform_predictor.py`, a real ordering/ID-tracking analysis) must supply; this module only turns already-real facts into coverpoint bins and classifies them honestly. (3) It imports no other module from `dv_harness` at all, including no other new module built in this same batch, so it stays usable regardless of which concurrently-built sibling module (`amba_master_slave_constraint_ir.py` included) eventually lands.

Proven by `dv_harness_tests/test_amba_functional_coverage_ir.py` (47 tests): the classifier's 7-way disjoint outcomes including a dedicated test proving all seven values are independently reachable from real input shapes and the derived-contradiction case; each of the four coverpoint builders' positive paths plus identity/duplicate/malformed negative controls; the meaningful-crosses-only skip-vs-track behavior (including the category-derived axis-snapshot path, proven both to skip a fully-explained cross with zero bins and to build real bins for a genuinely meaningful one); the assembled IR's cross-request wiring and its negative controls (missing axis names, an unrecognized category); a full JSON round-trip proof; an empty-build control; and the real CLI driven both in-process and as a real subprocess. `python -m pytest dv_harness_tests/test_amba_functional_coverage_ir.py -q` -> `47 passed`.

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

## Coherency Capability IR: ACE-Style Behavioral Capability, Never Inferred From a Protocol Name (2026-09-06)

`syoscb_compare_policy.py` already has a `_coherency_axis()` function, and `dv_harness/coherency_capability_ir.py` deliberately does NOT import it -- reading it first is exactly what confirmed the two answer different questions at different scopes. `_coherency_axis()` decides one narrow, SyoSil-specific fact: whether `AMBA_TRANSACTION_IR_FIELDS` has a slot for a coherency signal at all, so it can fill one field (`coherency_attributes`) of a compare-key schema (`MATCH_KEY_AXES`) -- and it correctly reports `AXIS_NO_IR_FIELD` for every protocol whose signal vocabulary carries an ACE-Lite signal, because no IR field exists to hold one. It was never meant to, and does not, model coherency BEHAVIOR.

`coherency_capability_ir.py` is a full behavioral capability model, a different and larger scope: four independently classified axes -- snoop-type support, coherency-domain membership, barrier-transaction support, and dirty/clean cache-line tracking -- each carrying its own status, evidence basis, and citation, answering "what can this DUT/interface actually DO" rather than "does a compare-key schema have a slot for this". Nothing in this module reads, imports, or re-derives anything from `syoscb_compare_policy.py`.

**The Evidence Truth Rule is enforced structurally, not only stated.** "ACE support must never be assumed from an AXI base protocol" is a property of `classify_axis(axis_name, evidence)`'s own signature -- it takes no `protocol` argument at all, so no code path can let a protocol string influence an axis's classification. `protocol`/`dut_name` are accepted only by `build_coherency_capability_ir()`, recorded on the resulting IR as informational context, and never consulted by classification -- proven directly (`test_axis_classification_never_reads_the_protocol_field`) by driving identical evidence under three different declared protocol strings and asserting byte-identical axis results, and by a companion test proving a bare `protocol="AXI_MM"` declaration with zero evidence still reports every axis `CAP_UNKNOWN`, never a guessed `NOT_SUPPORTED`.

Every axis is classified from exactly one of three real evidence kinds, each requiring a real citation: (1) `simulation_observed_values` -- real waveform/sim.log evidence that the capability's encoding was actually driven, the strongest proof this module recognizes; (2) `spec_statement` -- an explicit, cited spec/programming-guide sentence, either direction; (3) `signals_present`/`signals_checked` -- a real observed signal set compared against this module's own FIXED ACE/ACE-Lite witness-signal vocabulary (`AXIS_WITNESS_SIGNALS` -- ARSNOOP/AWSNOOP for snoop type; ARDOMAIN/AWDOMAIN plus the AC snoop channel for domain membership; ARBAR/AWBAR/WACK/RACK for barrier transactions; CRRESP plus the CR/CD channels for dirty/clean tracking -- the same "witness signal proves the field" convention `amba_transaction_ir.py`'s own `IR_FIELD_WITNESS_SIGNALS` already uses). A witness signal present proves `CAP_SUPPORTED`; the FULL witness set checked (a real superset, not a partial grep) and confirmed absent proves `CAP_NOT_SUPPORTED` -- a partial signal list can never manufacture a false-negative conclusion, proven directly. Absent all three, the honest answer is `CAP_UNKNOWN`, never a default. `CAP_NOT_APPLICABLE` is reachable only through an explicit caller `declared_not_applicable` (a real reason plus citation) -- never inferred by this module from a protocol name or family.

The whole-IR rollup (`derive_overall_capability()`) is worst-wins, the same "an unresolved fact must never silently disappear into an average" discipline this project applies everywhere: any axis at `CAP_UNKNOWN` forces the overall verdict to `COHERENCY_CAPABILITY_UNKNOWN` regardless of how many other axes are clean.

**File-safety scope held exactly.** This module imports nothing from the claimed file list or any other new module in this batch -- only `dv_harness.models.Status` (a stable, unclaimed module, imported solely to run `assert_no_verification_verdict_vocabulary()` at import time, holding this module's status/evidence-basis/overall vocabularies disjoint from a real stage verdict) and `dv_harness.connectivity.render_markdown_table` (this repo's one parameterized table renderer, reused rather than a fourth hand-rolled table loop -- also unclaimed and pre-existing outside this batch). No `dv-harness` CLI verb was added and `gates.py`/`cli.py`/`CLAUDE.md` were not touched, per this task's own file-safety scope; the front door is `python -m dv_harness.coherency_capability_ir --evidence <file.json> [--json]` (exit 0 every axis determined, 1 at least one axis `CAP_UNKNOWN`, 2 malformed/unreadable input).

**Deliberately bounded, and stated rather than implied closed.** This module classifies four capability axes from evidence a caller already has; it parses no RTL, runs no verible subprocess, and reads no waveform itself -- producing that evidence (a real port parse, a real VIP config dump, a real sim.log capture) is a caller's job. It decides, approves and arbitrates nothing beyond its own classification: no build, no job, no approval, and there is deliberately no stage gate -- a `CoherencyCapabilityIR` is an input to a human's coverage/architecture decision, never a substitute for one.

Proven by `dv_harness_tests/test_coherency_capability_ir.py` (31 tests): the positive path for all three evidence kinds (RTL signal presence, full-enumeration confirmed absence, spec statement both directions, simulation-observed values, declared-not-applicable); the two headline Evidence-Truth-Rule proofs described above; nine negative controls (an unknown axis name, a missing citation for each of the four evidence-declaration shapes, a partial signal enumeration proven unable to manufacture a false `NOT_SUPPORTED`, non-mapping evidence, an unrecognized axis key in a full evidence document); all four overall-rollup combinations (full support, no support, partial, not-applicable, and unknown-outranks-a-partially-clean picture); table rendering and IR-completeness checks; and four real CLI subprocess invocations covering all three exit codes plus a JSON round-trip. `python -m pytest dv_harness_tests/test_coherency_capability_ir.py -q` -> `31 passed`.

## AMBA command.txt extension (dv_harness/amba_command_txt_extension.py, 2026-09-06)

de_command_style_learning.py (this session) already classifies a DE command.txt line GENERICALLY -- what kind of statement it is, and a GLOBAL/DUT/FW/VIP branch-owner guess. It has no notion of AMBA fabric semantics at all: which master issued a transaction, which address region the transaction's address falls in beyond a bare number, or whether the statement executes inside a fork/join block alongside other masters' traffic running in parallel. amba_command_txt_extension.py closes that gap with a narrow, AMBA-specific compiler over the same kind of command record, answering four independent questions per command: operation (WRITE / READ / a recognized-but-neither macro / a structural non-transaction line / genuinely unclassifiable), master (which named master issued it), region (which named address region its address falls in), and parallel-group (which fork/join nesting group, if any, it executes inside).

The module is deliberately built to duck-type its input rather than import either de_command_style_learning.py or pattern_ir_assembly.py -- both are concurrent, differently-scoped modules in this same batch, and this batch's own file-safety rule forbids importing either. Every command record is therefore a plain dict (or any attribute-bearing object), read through small alias tables for its text (raw_text/text/source_text/line/statement/raw), its macro name (command_name/macro/name/command/statement_name), its operation (operation/semantic_operation/op), its master (master/master_name), its address (address/addr/base_address), its arguments (arguments/args), and its position (line_no/line_number/order/index). An explicit field always takes precedence over anything this module derives from raw text, so a producer that already resolved a fact is never second-guessed, and a producer that resolved nothing still gets an honest classification from the record's own text.

Master and region resolution never invent a value: master_registry and region_map are supplied entirely by the caller (real facts from wherever that caller's own project keeps them -- e.g. a fabric-discovery or port-registry artifact reduced to plain dicts before being handed in), and this module is only ever the compiler that reads a command's text against that data. An unrecognized master or region name reports one of several honestly DIFFERENT UNKNOWN-family statuses rather than a single catch-all or a guessed default: MASTER_UNKNOWN_NO_TOKEN (nothing master-shaped could even be extracted), MASTER_UNKNOWN_NO_REGISTRY_SUPPLIED (a candidate token was found but no registry was given to confirm it against), and MASTER_UNKNOWN_NOT_IN_REGISTRY (a candidate token was found and a registry was given, but the token matches nothing in it) are three different findings a reviewer needs to see differently. The region side adds a fourth honest outcome the master side cannot have: REGION_AMBIGUOUS_MULTIPLE_MATCH, when the caller's own region_map itself claims an address from more than one entry -- this module refuses to pick a winner rather than guess. Address parsing accepts only a real Verilog-style sized literal (32'h0002_0100) or an explicit integer/string address field, and explicitly refuses (reporting None with a cited reason) any literal carrying X/Z don't-care bits, rather than silently resolving them to zero.

Parallel-group membership is derived only from literal fork/join/join_any/join_none keyword text found in the records' own raw source (matched whole-word, so an identifier like forklift is never mistaken for the keyword), tracked as a real nesting stack across the ordered record sequence -- never inferred from a naming convention, and never guessed from record adjacency alone. An unbalanced join with no open fork, or a fork left unclosed at the end of the stream, is recorded as a warning on the compiled report rather than silently ignored or force-closed. Records are compiled in the order given unless every record in the batch carries a resolvable position field, in which case they are re-sorted by it -- a caller's own file order is never silently reshuffled by a guess about which field means "position" when that guess would be ambiguous.

Reuse is scoped tightly: AmbaCommandTxtExtensionReport.render_markdown() reuses dv_harness.connectivity.render_markdown_table, the repository's one parameterized table renderer, imported lazily inside the method rather than at module load. assert_no_verification_verdict_vocabulary() imports dv_harness.models lazily to check, rather than merely claim, that this module's four status vocabularies (OPERATION_STATUSES, MASTER_STATUSES, REGION_STATUSES, PARALLEL_GROUP_STATUSES) share no token with the harness's stage-gate Status verdict vocabulary. Neither de_command_style_learning.py, pattern_ir_assembly.py, nor any other file from this batch's claimed-file-safety list is imported anywhere in the module. The module performs no discovery of a project's own masters, slaves, or address map (that is amba_fabric_discovery.py/amba_port_registry.py's job, neither imported nor re-derived here), decides no VIP API, RTL content, or arbitration/security/QoS policy, and contains no performance/timing analysis of any kind. Tests live in dv_harness_tests/test_amba_command_txt_extension.py (22 cases: vocabulary hygiene, the core positive resolved-write/resolved-read/parallel-group path, and negative controls for every UNKNOWN/AMBIGUOUS status, a malformed region_map entry, a non-sequence input, and explicit-field precedence).

## AMBA Readiness Gates: the 9 Named Composite Gates from Section 71 (2026-09-06)

Section 71 of the AMBA M x N golden-flow source document names nine composite readiness gates and spells each out as a literal AND-formula in sections 72-80: L3_REFERENCE_READY, AMBA_PORT_REGISTRY_READY, AMBA_CONSTRAINT_READY, AMBA_CONNECTIVITY_READY, AMBA_VIP_BIND_READY, AMBA_SCOREBOARD_READY, AMBA_COVERAGE_READY, AMBA_TEST_GENERATION_READY, AMBA_SIGNOFF_READY. dv_harness/amba_readiness_gates.py is the evaluator, transcribing every AND-term verbatim from the document and applying this project's standard worst-wins discipline: a single UNMET condition blocks the whole gate as NOT_READY regardless of other clean conditions; UNKNOWN/NOT_AVAILABLE (or a condition never supplied at all) makes the gate INCOMPLETE_EVIDENCE rather than either READY or NOT_READY. AMBA_TEST_GENERATION_READY references three other gates as AND-terms; all nine are evaluated in the document's fixed order so those sub-gates are already computed, with an explicit caller override always outranking the derived value. Proven by 26 tests in dv_harness_tests/test_amba_readiness_gates.py covering the positive path, worst-wins negative controls, cross-gate propagation, malformed-input refusals, and CLI subprocess exit codes.

## Fabric Progress IR: Deadlock/Livelock Risk Over a Caller-Declared Wait Graph (2026-09-06)

This project's real AMBA/SyoSil integration family (amba_fabric_discovery.py, amba_port_registry.py, amba_fabric_analysis.py, amba_transaction_ir.py, amba_route_transform_predictor.py, amba_scoreboard_env.py, syoscb_*) already models fabric TOPOLOGY, TRANSACTION content, and ROUTING/TRANSFORM prediction -- none of it asks whether a caller-declared wait-for relationship among fabric agents forms a real CIRCULAR WAIT, and none of it tracks credit/outstanding-transaction counts toward exhaustion. A repo-wide check found no deadlock/livelock/circular_wait/credit_exhaust/outstanding_exhaust detector anywhere -- "deadlock" appeared only inside free-text failure-classifier regexes in system_failure_taxonomy.py/command_error_taxonomy.py, which classify already-REPORTED failure TEXT and neither build nor walk a dependency graph. dv_harness/fabric_progress_ir.py is that missing analysis, and only that.

Two independent, real graph/arithmetic analyses over facts a caller already has -- never self-derived from RTL, a VIP transaction stream, or any other producer in this project. analyze_resource_dependency_cycle(facts) takes a generic list of {resource, held_by, waiting_for} records: resource is the arbitrated fabric resource the fact is about (a port, a shared bus, a buffer slot, an arbitration grant), held_by is the agent presently holding it, and waiting_for names zero, one, or several OTHER resources that same holder is blocked waiting to acquire. This module never invents a circular-wait scenario -- it builds a resource-to-holder map from the caller's own resource/held_by pairs, resolves each waiting_for entry to the holder of that named resource, and runs real cycle detection over the resulting holder-level wait-for graph. analyze_credit_outstanding(facts) takes a generic list of {resource, credit_available, credit_max, outstanding_count, outstanding_limit} records (all fields but resource optional); exhaustion is decided from the caller's OWN numbers -- credit_available <= 0 is CREDIT_EXHAUSTED, outstanding_count >= outstanding_limit is OUTSTANDING_EXHAUSTED -- neither threshold, neither axis's presence, nor either number is invented here.

analyze_fabric_progress() composes both into one FabricProgressIR, folding an overall_status by strict WORST-WINS (a real risk finding on EITHER axis outranks everything; an evidence GAP on either axis, with no real risk found anywhere, outranks a clean report on both) -- the same no-averaging discipline golden_flow_readiness.combine_readiness()/spec_vplan_readiness_gate.py/system_readiness_gates.py already apply to their own composite folds, never re-derived a second way here.

The Evidence Truth Rule, applied literally: never claim deadlock-freedom (or exhaustion-freedom) from an INCOMPLETE graph. A waiting_for entry naming a resource this module has no {resource, held_by} fact for at all, or one whose holder is AMBIGUOUS (two facts declare two different holders for the same resource -- a real evidence conflict this module never arbitrates, the same arbitration boundary requirement_contract.py/design_knowledge_correlation.py already keep for their own conflicting-claim findings), is reported as an UNRESOLVED dependency. Finding zero cycles over a graph carrying even one unresolved dependency reports INSUFFICIENT_EVIDENCE, never NO_CYCLE_DETECTED -- an absence of proof is not proof of absence.

Proven by dv_harness_tests/test_fabric_progress_ir.py (33 tests): a real injected circular-wait cycle is detected; a clean acyclic graph reports NO_CYCLE_DETECTED; an unresolved dependency (a named resource with no fact, or an ambiguous dual-holder claim) is proven to force INSUFFICIENT_EVIDENCE rather than a false-clean result; both credit and outstanding exhaustion are proven from real caller numbers on both the exhausted and non-exhausted sides; and the worst-wins composite fold is proven against every combination of risk-found/gap/clean on both axes.

Disclosed residual: this module builds and analyzes a graph over facts it is handed -- it derives no topology or dependency fact of its own from RTL or a live simulation, and references no approval/governance mechanism.

## Security Policy IR: an Access Matrix Built Only From Cited Evidence (2026-09-06)

A repo-wide grep for SecurityPolicyIR, security_policy, TrustZone, secure_privileged, access_matrix, S_NS/ARM_TZ, and the real AMBA/SyoSil/system module family (amba_fabric_discovery.py, amba_port_registry.py, amba_fabric_analysis.py, amba_transaction_ir.py, amba_route_transform_predictor.py, amba_scoreboard_env.py, syoscb_compare_policy.py, syoscb_topology_plan.py, syoscb_result_taxonomy.py, syoscb_phase1_report.py, syoscb_source_audit.py, system_resource_inventory.py, system_topology_analysis.py, system_scheduling_plan.py) found no security/privilege PERMISSION concept anywhere in this repo: the AMBA family models fabric topology, transaction routing, and route-transform prediction, never a security axis; the SyoSil family models scoreboard compare/topology/result-taxonomy, an unrelated domain; the system_* family models cross-subsystem resource ownership and topology, not per-access security policy. dv_harness/security_policy_ir.py is new, standalone territory -- it imports nothing from any of those files or from any other new module built in this same batch; its only import is dv_harness.models, for the vocabulary-disjointness check several sibling modules already run against it.

A SecurityPolicyIR is a set of caller-declared ACCESS RULES, each stating an ALLOWED or DENIED decision for a (master, region, secure, privileged) combination -- or a wildcard subset of it -- together with a REQUIRED, non-empty evidence citation (a spec section, an RTL file:line, a register programming-guide reference). A rule with no evidence citation is refused outright (SecurityPolicyIRError) rather than silently accepted: an uncited access-permission claim is exactly the "confident guess" the Evidence Truth Rule forbids, and getting a security-permission fact wrong is higher-consequence than most facts this harness handles. Nothing here infers a decision from a master/region NAME, a naming convention, or any other heuristic -- every decision traces to a rule a caller explicitly declared, with its citation carried through to every classification result that uses it.

An access combination no declared rule covers is classified UNKNOWN -- never defaulted to ALLOWED (a fail-open default-allow guess on a security matrix is exactly the kind of silent default this project forbids) and never defaulted to DENIED either (that would fabricate a security decision nobody declared). A caller MAY declare an explicit, cited default_decision for the whole matrix (e.g. "undeclared regions/masters default DENY, per <spec citation>") -- applied only when no specific rule matches, always distinguishable in the result from a matched-rule decision, and itself requires a citation like any other rule.

Two rules of equal specificity naming the SAME access combination with DIFFERENT decisions is a genuine, uncited-into-agreement CONFLICT -- this module never picks a winner (no source-authority order is declared here; that arbitration, if wanted, belongs to a caller invoking a real conflict-resolution mechanism such as source_authority.py, deliberately not imported here). A conflict classifies as UNKNOWN and names both conflicting rules and their citations.

The negative-test verification helper checks that a supplied test result actually OBSERVED a denial for an access the matrix says should be denied -- it never assumes a negative test passed just because a verdict field says so; it looks for the real observed evidence of the denial (e.g. a recorded error response, an assertion firing) rather than trusting a bare PASS label.

Proven by dv_harness_tests/test_security_policy_ir.py (34 tests): a matched rule classifies correctly with its citation carried through; an uncited rule is refused at construction; an uncovered combination is UNKNOWN both with and without a declared default; a conflicting pair of equal-specificity rules is proven UNKNOWN naming both; and the negative-test verification helper is proven to distinguish a real observed denial from a bare PASS-labeled result that never actually exercised the denial path.

Disclosed residual: this module classifies from caller-declared, cited rules only -- it derives no security fact of its own from RTL or a live simulation, arbitrates no conflict, and references no approval/governance mechanism.

## AMBA Performance Calculator: Pure Arithmetic Over Caller-Supplied Numbers, Never an Invented Peak (2026-09-06)

This harness has no live simulator and no formal tool, so its only real timing evidence is whatever an already-produced artifact (`fsdb_report.py` output, a sim.log, or a caller-supplied trace record) already contains. Nothing in this repo did the ONE-LEVEL-ABOVE-`fsdb_report.py` arithmetic a performance report needs: bandwidth/throughput/latency-percentile/outstanding-count/stall-ratio/utilization computation over real, already-extracted numbers, with the three rules this domain's fabrication risk demands enforced in code rather than left as a docstring promise. `dv_harness/amba_performance_calculator.py` is that arithmetic layer, and only that.

**Three rules, enforced as code, not prose.** (a) A numeric threshold/target is NEVER invented — `evaluate_against_target()` reports `NOT_APPLICABLE`, never a fabricated pass/fail, whenever no caller-declared `target_value` exists. (b) An unprovable peak/baseline/metric yields `UNKNOWN`, never a computed-looking number — every function returns a typed result (`MetricResult`/`LatencyPercentileReport`/`OutstandingStatsResult`/`TargetEvaluationResult`) carrying an explicit `status` in `{COMPUTED, UNKNOWN, NOT_APPLICABLE}` (asserted disjoint from `dv_harness.models.Status` at import time), and an empty/missing input list always reports `UNKNOWN` with a real reason rather than a silent zero or a crash. `bandwidth_utilization()` is the sharpest instance: it MUST report `UNKNOWN` when no caller-supplied, already-proven peak bandwidth is provided — it never divides against an invented or reverse-engineered ceiling. (c) Functional correctness ALWAYS outranks a performance PASS — `decide_overall_verdict()` is a hard PRECEDENCE branch over the real `models.Status.PASS`/`FAIL` vocabulary (reused, not re-spelled): a functional FAIL is the overall verdict regardless of how good the performance numbers are, and a performance PASS can never promote a functionally-incorrect result to an overall PASS. This is a branch, never a weighted score.

**Data shapes.** `LatencyDefinitionIR` states what "latency" means for a measurement (`ISSUE_TO_FIRST_BEAT` / `ISSUE_TO_LAST_BEAT` / `REQUEST_TO_RESPONSE`) — NEVER assumed, mandatory on every latency-percentile call, because different callers mean different things by "latency" and silently picking one would misrepresent whichever quantity the underlying evidence actually measured. `PerformanceSampleIR` is one real observed transaction/window sample (counts, byte sizes, start/end timestamps, all caller-supplied — this module never derives one itself). `PortPerformanceIR`/`PathPerformanceIR` are per-port/per-path aggregates built by `aggregate_port_performance()`, which calls only the module's own pure functions — no metric is ever computed a second, disagreeing way. `PerformanceWindowIR` is a time window over which samples were aggregated; `PerformanceCurveIR` is an ordered series of windows for a future ramp/saturation curve — this module only HOLDS that data shape, it does not generate the ramp itself (that needs a live traffic generator, explicitly out of scope: this harness has no live simulator to validate one against).

**Pure functions, each over real caller-supplied numbers only**: `compute_bandwidth`/`compute_throughput` (bytes or transactions over time), `compute_latency_percentiles` (p50/p90/p95/p99 via linear-interpolation percentile arithmetic, no third-party dependency, mandatory `latency_definition`), `compute_outstanding_stats` (average/peak over a real list of observed outstanding counts), `compute_stall_ratio`/`compute_utilization` (stalled-or-busy cycles over total cycles, both caller-supplied — an over-1.0 ratio is reported as real evidence with a data-quality `reason` rather than clamped or hidden), `bandwidth_utilization`, `evaluate_against_target`, and `decide_overall_verdict`.

**Deliberately bounded, and stated rather than implied closed.** It never reads an FSDB/waveform file, never monitors a live signal, never generates traffic, and never runs a simulation — all explicitly out of scope for this batch. It decides nothing beyond the one hard precedence rule in (c): no gate, no approval, no build/regression/LSF submission, and there is deliberately no stage gate.

Proven by `dv_harness_tests/test_amba_performance_calculator.py` (51 tests) against small real synthetic transaction-trace fixtures built directly in the test file: core positive paths for every function; the required negative controls proving UNKNOWN on an empty/missing sample list rather than a crash or a fabricated zero; the headline `bandwidth_utilization`-is-UNKNOWN-with-no-peak-supplied test; `evaluate_against_target`'s NOT_APPLICABLE-with-no-target test; and the functional-correctness-outranks-performance test (functional FAIL + performance PASS still reads overall FAIL), plus its sibling proving an unresolved/unrecognized functional verdict is never silently promoted to PASS by a good performance number. `python -m pytest dv_harness_tests/test_amba_performance_calculator.py -q` → `51 passed`.

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

## AMBA Performance Classification: Saturation / Bottleneck-Candidate / Anomaly / Regression-Delta (2026-09-06)

`amba_performance_calculator.py` already does the raw PERFORMANCE ARITHMETIC (bandwidth, throughput, latency percentiles, utilization, the hard functional-correctness-outranks-performance precedence). Nothing in this repo turned those numbers into a CLASSIFICATION: is a port/path actually SATURATED, what is the leading bottleneck CANDIDATE (not a confirmed root cause), does an observed sample DEVIATE from a real historical baseline, and did a metric IMPROVE/REGRESS/stay UNCHANGED between two measured periods. `dv_harness/amba_performance_classification.py` is that classification layer, built under the same three hard rules `amba_performance_calculator.py` already enforces in code (never a docstring promise): a threshold/target/baseline is never invented (`NOT_APPLICABLE` when absent), an unprovable metric yields `UNKNOWN` (never a computed-looking number), and functional correctness always outranks a performance PASS.

**Four classifiers, each requiring AT LEAST TWO correlated real caller-supplied metrics -- never one metric alone.** `classify_saturation()` requires utilization sitting at/above a caller-declared fraction of a caller-declared max ceiling ALONGSIDE a real rising-latency or rising-stall trend signal; either metric alone reports `UNKNOWN` (never a guessed SATURATED/NOT_SATURATED), and the two metrics DISAGREEING (one signals saturation, the other does not) reports `INDETERMINATE`, never silently resolved in either direction. Asserting a rising trend as `True` with no cited evidence is refused outright (`PerformanceClassificationError`), never silently accepted. `identify_bottleneck_candidate()` builds a structured `{hypothesis, evidence, confidence, gap, next_best_action}` record -- matching this project's existing Hypothesis -> Evidence -> Confidence -> Gap -> Next-Best-Action discipline (see `inference.py` for the pattern; deliberately NOT imported, since that module's `score_confidence()` counts generic corroborating evidence for an arbitrary claim, and this domain needs its own correlated-metric-count-based confidence derivation instead) -- and refuses (raises) to construct one from fewer than 2 real, non-empty, independently-cited correlated evidence entries: a hypothesis resting on one metric is never reported as a candidate. `detect_anomaly()` compares a real observed sample against a real caller-supplied baseline (a historical range, or a mean/stddev distribution plus a caller-declared deviation threshold); an absent baseline is `NOT_APPLICABLE` (a baseline is never fabricated from the observation alone), and a missing observation is `UNKNOWN` regardless of baseline availability. `compute_regression_delta()` compares two real measured samples/periods for one named metric and reports IMPROVED/REGRESSED/UNCHANGED/INCONCLUSIVE -- INCONCLUSIVE, never a fabricated percentage, whenever the two samples declare different units, declare different measurement windows, or the baseline is zero (a percent-change against zero is mathematically undefined, not silently reported as 0% or as an arbitrary large number).

**Reuse, not reinvention, of the functional-correctness precedence.** `decide_overall_performance_verdict()` does not reimplement rule (c) a second time -- it imports and calls `amba_performance_calculator.decide_overall_verdict()` directly, mapping this module's own regression-delta verdict onto that function's `performance_verdict` parameter (IMPROVED/UNCHANGED become a performance PASS, REGRESSED becomes a performance FAIL, INCONCLUSIVE/UNKNOWN/absent are passed through as "no performance verdict was evaluated"). There is exactly one place in this project that decides "does functional correctness outrank a performance result", and this module calls it rather than duplicating it: a functionally-FAILed transaction whose own regression delta reports IMPROVED still resolves to an overall FAIL.

**Jain's fairness index, included because this batch's source document calls for a fairness/QoS-inversion check.** `compute_jains_fairness_index()` is the real, well-known one-line formula (`J = (sum(x_i))**2 / (n * sum(x_i**2))`, Jain/Chiu/Hawe 1984) over a real per-requester allocation/throughput map. It refuses to compute -- reports `UNKNOWN`, never a value silently computed over the subset that happened to report -- the instant ANY declared requester's value is absent, and reports `UNKNOWN` rather than a fabricated `1.0` on the genuinely undefined all-zero (0/0) case; a single requester is honestly `NOT_APPLICABLE` (fairness across one requester is not a meaningful question).

**Deliberately bounded, and stated rather than implied closed.** This module reads no FSDB/waveform file, monitors no live signal, generates no traffic, and runs no simulation -- all explicitly out of scope for this batch, since this harness has no live simulator to validate any of that against; it imports nothing from `dv_harness` beyond `amba_performance_calculator`'s reused precedence function and its own status-token constants, plus `models.Status` for a vocabulary-collision check. It decides, approves, and arbitrates nothing beyond its own classification: no gate, no approval, no build/regression/LSF submission, and no CLI verb was added.

Proven by `dv_harness_tests/test_amba_performance_classification.py` (54 tests): the core positive path for all four classifiers plus the fairness index; the required negative controls -- a single metric never classifies saturation either way, no declared ceiling is `NOT_APPLICABLE`, a missing observation is `UNKNOWN`, a single-evidence-item bottleneck candidate is refused, an absent baseline anomaly check is `NOT_APPLICABLE`, a zero-baseline regression delta is `INCONCLUSIVE` rather than a fabricated percentage, incomplete per-requester fairness data is refused rather than silently computed over the partial set, and an all-zero fairness input is `UNKNOWN` rather than a fabricated perfect score; and the headline functional-correctness-outranks-performance proof, driving a real `REGRESSION_IMPROVED` performance result alongside a functional FAIL to a confirmed overall FAIL through the reused `amba_performance_calculator.decide_overall_verdict()`.

## AMBA Performance Readiness Gates: BUS_PERFORMANCE_READY / BUS_PERFORMANCE_SIGNOFF_READY (2026-09-06)

Two composite gates -- `BUS_PERFORMANCE_READY` and `BUS_PERFORMANCE_SIGNOFF_READY` -- each a real AND-formula over caller-supplied condition inputs, `dv_harness/amba_performance_readiness_gates.py` matches this project's other composite-gate modules (`amba_readiness_gates.py`, `subsystem_maturity_gate.py`, `functional_coverage_signoff.py`, `spec_vplan_readiness_gate.py`, `system_readiness_gates.py`) in shape and discipline. This is the highest fabrication-risk domain in this project -- performance -- and this harness has no live simulator and no formal timing tool, so this module never computes, measures, or estimates a single performance number: it only folds already-real `{"condition_name": ..., "status": ...}` records a caller supplies. It deliberately imports NOTHING from `amba_performance_calculator.py`, `amba_performance_requirement_checker.py`, or `amba_performance_classification.py` -- it never assumes any of those three modules exist, ran, or finished cleanly in the same batch. Whatever those modules concluded reaches this gate only as a generic, duck-typed condition record naming their conceptual output (e.g. `Performance_Target_Declared`, `Performance_Requirement_Evaluation_Complete`) -- this module never inspects a waveform, a sim.log, or an `fsdb_report.py` output itself, and never decides what counts as satisfying a named condition.

**Three fabrication-risk rules are enforced IN CODE here, never left as a docstring promise.** (a) A numeric threshold/target is NEVER invented by this module -- it has no field anywhere for a number; a caller either supplies a condition record saying whether a target was declared (`Performance_Target_Declared`: MET/UNMET/UNKNOWN/NOT_AVAILABLE) or the whole performance dimension is marked `NOT_APPLICABLE` for a project/path that is not performance-critical. (b) An unprovable peak/baseline/metric condition yields UNKNOWN/NOT_AVAILABLE, which this module folds to `INCOMPLETE_EVIDENCE` -- never a computed-looking percentage, never silently promoted to READY (GF-AT-28), and never forced into a confirmed NOT_READY it was never proven to be. (c) Functional correctness ALWAYS outranks a performance PASS -- every gate's own AND-formula includes a `Functional_Correctness_Confirmed` term; because the fold is a strict AND (worst-wins, never averaged or weighted), a functionally-incorrect transaction blocks the WHOLE gate as NOT_READY regardless of how many performance conditions on that same gate read MET -- a hard precedence enforced by the fold's own arithmetic, never a score a high performance number could outweigh.

**Discipline matches this project's other composite-gate modules: worst-wins, never averaged.** A single UNMET condition blocks the WHOLE gate as NOT_READY regardless of how many other conditions on that gate are clean. Only once no condition is UNMET does an UNKNOWN/NOT_AVAILABLE condition -- or a condition nobody supplied evidence for at all -- make the gate `INCOMPLETE_EVIDENCE` rather than either READY or NOT_READY. An explicit, CALLER-DECLARED `NOT_APPLICABLE` outcome is supported for a project/path that is not performance-critical -- never inferred by this module from the condition list itself (there is no rule like "no performance conditions supplied means not applicable", which would silently read an unmeasured project as one with nothing to measure); it is only ever produced when the caller explicitly declares `not_applicable=True` with a real, non-empty `reason`.

`BUS_PERFORMANCE_SIGNOFF_READY`'s own AND-formula names `BUS_PERFORMANCE_READY` as one of its terms, exactly as `AMBA_TEST_GENERATION_READY` names three earlier gates in `amba_readiness_gates.py`: the two gates are evaluated in a fixed order (READY, then SIGNOFF_READY) so that sub-gate reference is already computed by the time it is needed, and an explicit caller-supplied condition record naming `BUS_PERFORMANCE_READY` directly always outranks the derived sub-gate verdict -- the same "real evidence outranks a derived value" precedence this project's Source Authority Order already applies everywhere else.

Proven by `dv_harness_tests/test_amba_performance_readiness_gates.py` (31 tests): the positive path for both gates; the worst-wins negative control (a single UNMET condition blocks the gate regardless of how many others are clean); the functional-correctness-outranks-performance headline proof; `INCOMPLETE_EVIDENCE` proven distinct from `NOT_READY` on an UNKNOWN/absent condition; the explicit caller-declared `NOT_APPLICABLE` path proven never self-inferred; and `BUS_PERFORMANCE_SIGNOFF_READY`'s sub-gate reference proven to use a caller override when supplied and the derived `BUS_PERFORMANCE_READY` value otherwise.

**Disclosed residual**: this module folds caller-supplied conditions only -- it derives no performance fact of its own, runs no build/regression/LSF submission, and references no approval/governance mechanism.
