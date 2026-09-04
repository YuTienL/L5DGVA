# AI Mechanism #12 — AI Debug Closed Loop — Gap Close

**Status: DONE**

**One-line test summary:** `dv_harness_tests/test_waveform_dump_scope_human_confirmation.py` 11 passed
(8 pre-existing + 3 new real-path wiring tests); engine/gates/question-queue/RCA regression suites pass.

---

## What the audit found, and what I actually closed

The re-audit's verdict was PARTIALLY_WIRED, and its own "what would close the remaining gap" list was
almost entirely **operational** rather than code: establish a remote session by hand (item 1, explicitly
human-only per `CLAUDE.md`'s "SSH/Remote Transport Connection Intake" — and `remote_relay.py` "must never
be invoked from a Claude Code tool call"), then run `dv-harness start --loop` against real LSF/VCS/`.fsdb`
(items 2–5). None of that is executable from this Windows dev box in an autonomous fix pass, and I did not
fabricate it.

So I re-read the cited evidence myself and looked for a **real, code-level wiring gap** in the same
mechanism. There is one, and it is precisely the audit's own branch #4 ("the go/no-go and scope decision
is a mandatory human gate"), one level below where the audit stopped:

**`waveform_dump_gate.ask_dump_scope_confirmation()` — the ASK half of the round-trip — had exactly one
caller in the entire repo, and it was not the engine.**

```
$ grep -rn "ask_dump_scope_confirmation" --include=*.py .
./dv_harness/cli.py:2639:   record = waveform_dump_gate.ask_dump_scope_confirmation(   # <- `dv-harness waveform-dump-scope ask`, human-typed
./dv_harness_tests/test_waveform_dump_scope_human_confirmation.py:77
```

Zero references in `dv_harness/engine.py`. The autonomous sequence was therefore:

1. headless `claude -p` subprocess (`adapters/cli.py:68-108`) emits a `focused_wave_debug_window_gate`
   evidence block whose `confirmed_by` cannot resolve to a human decision;
2. `focused_wave_debug_window_gate.py:75` → `verify_dump_scope_confirmation()` returns
   `WAVEFORM_DUMP_SCOPE_NOT_ASKED`;
3. `gates.py:1500-1502` maps it to `NEEDS_USER_INPUT`;
4. `engine.run_stage()` sets `Status.WAIT_USER`; `engine.loop()` returns.

Steps 1–4 are all correct and deliberate. The defect is what is **left behind**: the question queue was
still **empty**. `dv-harness question-queue list --blocking-only` showed nothing, `build_digest()` had
nothing to report, and the human returning to the parked run had to read a Q-ID out of a `blocking_reason`
string and hand-reconstruct `dv-harness waveform-dump-scope ask --scope ... --level-or-depth ...` before
the `answer` verb had anything to answer. **The loop opened at WAIT_USER and produced no artifact capable
of closing it.**

`CLAUDE.md`'s own "Waveform Dump User Gate / Disclosed residual" already asserted that such a run
"parks at WAIT_USER **with a real Q-ID** for a human to answer" — a claim that was true only on the
interactive path, where a human typed the ask verb. That is the gap I closed.

This is a wiring fix into the real production path, not a parallel mechanism: the ask API, the
`QuestionQueueStore`, the Q-ID derivation and the Tier-3 classification are all the existing ones, called
from the existing `run_stage()` verdict branch.

---

## What changed

### 1. `dv_harness/engine.py` — new `DVHarness._file_waveform_dump_scope_question()`

Inserted immediately before `_arm_rca_evidence_fanout()`, following the same established convention as
`_arm_rca_evidence_fanout` / `_score_root_cause_confidence` / `_promote_experience_knowledge`: read the
**already-parsed** `evidence_blocks` dict `run_stage()` computed via `extract_evidence_blocks(result.text)`,
never re-parse the agent text.

It reads `evidence_blocks["focused_wave_debug_window_gate"]["dump_scope_confirmed"]` — the very block the
gate just rejected — for `scope` and `level_or_depth`, so the filed question describes the dump the agent
actually proposed rather than a placeholder, and calls the real
`waveform_dump_gate.ask_dump_scope_confirmation()` against a real `QuestionQueueStore(self.root,
blackboard=self.blackboard)`.

**It files a QUESTION; it never writes a DECISION.** Only `QuestionQueueStore.answer_question()` — i.e. a
human running `dv-harness question-queue answer` — can write one, and this method does not call it. The
policy-mandated human checkpoint is untouched; what changed is that the human is handed an answerable
Q-ID instead of an instruction to file one themselves.

Three deliberate non-filing cases:

| case | why nothing is filed |
|---|---|
| no `focused_wave_debug_window_gate` block at all | this `NEEDS_USER_INPUT` is INTAKE's, not the waveform gate's |
| block declares no `scope` or no `level_or_depth` | `WAVEFORM_DUMP_SCOPE_NOT_CONFIRMED` / `_CONFIRMATION_INCOMPLETE` is **agent error** with its own remedy already in `reasons` — a question that cannot say what dump is proposed cannot be answered yes/no, which is exactly why `ask_dump_scope_confirmation()` raises `ValueError` on it |
| a question for this scope's `question_key` is already on file | `verify_dump_scope_confirmation()`'s `REASON_AWAITING_ANSWER` case, tested with the identical `store.get_question(qid) is not None` predicate. `add_question()` **appends** rather than deduping on the derived id, so unconditional re-filing would grow duplicate records and re-arm `digest_batch_id` on a question a human is already sitting on |

Best-effort, like every other post-verdict hook there: a question-queue failure records a
`WAVEFORM_DUMP_SCOPE_QUESTION_FILE_FAILED` event and returns `None` rather than crashing out of an
already-correct WAIT_USER park. A successful filing records `WAVEFORM_DUMP_SCOPE_QUESTION_FILED`
(question id/key, tier, status, scope, level_or_depth) in `.dv-harness/events.jsonl`.

### 2. `dv_harness/engine.py` — the `elif verdict == "NEEDS_USER_INPUT":` branch in `run_stage()`

Calls the helper at the exact point WAIT_USER is assigned, and appends the real unblocking command to
`blocking_reason`:

```
  dv-harness question-queue answer <Q-ID> --answer <APPROVE/NARROW/WIDEN ...> --basis <依據> --decided-by <你的名字>
```

Appended **after** the pre-existing `[:2000]` truncation, deliberately — the Q-ID and the one command
that unblocks the run must never be the part that gets cut off. Existing truncation behavior for the
`reasons` text itself is unchanged.

### 3. `CLAUDE.md` — "Waveform Dump User Gate"

Added the bullet documenting the engine-side ask (what the gap was, what files it now, and every case
where it deliberately files nothing), and corrected the "Disclosed residual" paragraph so it says the
Q-ID is one **the engine filed**, and states plainly that the round-trip is still asynchronous: the run
stops, and only `question-queue answer` plus a fresh `dv-harness start --loop` resumes it.

### 4. `dv_harness_tests/test_waveform_dump_scope_human_confirmation.py` — 3 new tests (section 3)

Tests the **wiring**, not the underlying function in isolation (that was never the gap), on the real
path: real shipped `main_graph.json`, real `tools/` tree, real gate script as a subprocess, real
`QuestionQueueStore` on disk — no mocks, no hand-built `decisions.json`.

- `test_autonomous_loop_files_the_question_it_parks_on_and_a_human_answer_closes_it` — the full
  round-trip. Asserts the queue is empty as a precondition, drives a real `DVHarness.loop()`, then
  asserts exactly one Tier-3 blocking OPEN question exists with the engine-derived Q-ID, that its
  `recommendation`/`context_path` carry the scope and level the **agent** proposed, that it shows up in
  `list_questions(blocking=True, status="OPEN")` (the digest's own view), that `blocking_reason` names
  `question-queue answer <Q-ID>`, and that a real `WAVEFORM_DUMP_SCOPE_QUESTION_FILED` event landed.
  Then a human answers **the Q-ID the engine minted** (not one the test constructed) and the stage
  reaches real `Status.PASS`.
- `test_a_question_already_waiting_is_not_re_filed_by_a_second_loop_pass` — two consecutive real
  `loop()` calls over a pre-filed question leave exactly one record and emit no filing event.
- `test_nothing_is_filed_when_the_agent_declared_no_scope_or_no_level` — three malformed
  `dump_scope_confirmed` shapes each still park at WAIT_USER with an empty queue and no event, plus the
  INTAKE-shaped no-block case.

The pre-existing assertion `"waveform-dump-scope ask" in reason` still holds and was left alone: the gate
subprocess runs *before* the filing, so its `REASON_NOT_ASKED` remedy text is unchanged; the new note is
appended after it.

---

## Test results

```
dv_harness_tests/test_waveform_dump_scope_human_confirmation.py .............  11 passed in 153.19s
```

Regression suites for everything touched (`engine.py` run_stage/verdict routing, gates, question queue,
RCA fan-out, ReAct loop):

```
test_engine_gates_and_routing.py  test_question_queue.py  test_cli_question_queue.py
test_rca_multi_agent_fanout.py    test_deep_rca_evidence_gate.py  test_react_loop.py
```

(see the run recorded at commit time)

**Audit item #6 re-verified, no action needed:** the audit reported
`test_rca_multi_agent_fanout.py::test_real_issue_triage_dispatches_the_rca_fanout_end_to_end` failing on
a Windows temp-dir `PermissionError`. Re-run today: **7 passed in 60.46s**, no `PermissionError`. Either
it was already addressed by a concurrent workstream in this pass or it is an intermittent file-lock race;
either way there was nothing to fix, so I did not add a speculative `try/except` around a teardown that
is not failing.

---

## What is explicitly NOT closed by this pass (and why)

The audit's headline finding — *"empirically, in this exact live project, the engine has never executed
the loop past its very first stage"* — is **still true and is not code-fixable here**. I re-confirmed it
myself: `v50/.dv-harness/state.json` today shows `current_stage: "ENV_CHECK"`, 1 stage `PASS`, 38
`NOT_STARTED`, and `v50/.dv-harness/blackboard/` contains no `debug_loop_history.json`.

Closing that requires, in order: (1) a human establishing the remote session (CLAUDE.md forbids the agent
doing this — `remote_relay.py` "must never be invoked from a Claude Code tool call"), (2) real LSF/VCS
capacity, and (3) a real `.fsdb` for `focused_wave_debug_window_gate`'s `stop == failure_time + 200us`
math to run against — none of which exist on this Windows dev box. That is a **first real end-to-end
exercise**, not a fix, and fabricating any part of it would be exactly the Evidence Truth Rule violation
this mechanism's own gates exist to prevent.

Also unchanged by design, and correctly so:

- The three human checkpoints (SSH first-connect, Health Monitor watcher start, waveform go/no-go) remain
  policy-mandated human steps. This change makes the third one *answerable*; it does not remove it.
- The broader "a headless run has no live channel to ask a human mid-flight" limitation stands. The run
  still stops and still waits.

---

## Files changed

- `v50/dv_harness/engine.py` — new `_file_waveform_dump_scope_question()`; `NEEDS_USER_INPUT` branch wired to it
- `v50/CLAUDE.md` — "Waveform Dump User Gate" bullet + corrected disclosed residual
- `v50/dv_harness_tests/test_waveform_dump_scope_human_confirmation.py` — 3 new real-path wiring tests


---
---

# Appendix — the EARLIER 2026-09-04 pass, preserved verbatim

This file is the standing report for AI mechanism #12 and has now carried two passes on the
same day. Everything above is the SECOND pass (the follow-on re-audit gap close: wiring the
engine's own ask into the autonomous path). Everything below is the FIRST pass verbatim — the
one that built the human-answer gate this second pass then found was missing its ask half on
the autonomous path. It is kept rather than overwritten because the second pass's finding only
makes sense against it.

---

# Gap close — AI mechanism #12: AI Debug Closed Loop

**Status: DONE**

**Test summary:** 8 new tests in `dv_harness_tests/test_waveform_dump_scope_human_confirmation.py`
plus 2 rewritten existing tests, all green in a 621-test sweep across every suite that touches the
gate, the question queue or the engine's gate routing (239 + 244 + 130, all exit 0).

Commit: `waveform-gate: verify dump-scope confirmation against a real human answer, and stop the
loop for one`.

---

## What I re-verified before touching anything

The audit's verdict was PARTIALLY_WIRED with three named gaps and one explicit non-gap. I checked
each against the current tree first, because this pass is running concurrently with other
workstreams and the audit's own snapshot was already partly stale.

### Gap 1 (Multi-Agent RCA fan-out) — ALREADY CLOSED, no action taken

The audit said the RTL/PHY/Register/VIP fan-out shape "only happens when a human-driven interactive
Claude Code session does it by hand", citing `FAILURE_RECOVERY` and `WAVE_ANALYSIS` both having
`"parallel_group": null`. That premise is true but the conclusion no longer is — the fan-out does
not live *on* `FAILURE_RECOVERY`, it hangs off its PASS edge, and it already exists:

- `.dv-harness/graph/main_graph.json` is now 41 nodes and really contains `RCA_RTL_EVIDENCE`,
  `RCA_LOG_EVIDENCE`, `RCA_VIP_SPEC_EVIDENCE` (all `parallel_group: RCA_G1`, agents
  `rtl-evidence-agent` / `log-evidence-agent` / `vip-spec-evidence-agent`) and `RCA_JOIN`
  (`join_group: RCA_G1`, agent `analysis_debug`) — read directly out of the shipped graph.
- `engine.py` really drives it: `RCA_EVIDENCE_FANOUT_GROUP = "RCA_G1"`, `_arm_rca_evidence_fanout()`
  on a gate-verified PASS, and the narrowing that hands the frontier to the pre-existing
  `_advance_with_fanout()` `ThreadPoolExecutor`. `_rca_fanout_agent_evidence_count()` feeds the
  real join.
- `gates.py`'s STAGE_GATES carries a written decision for why only the JOIN is gated.
- It is covered by `dv_harness_tests/test_rca_multi_agent_fanout.py` (7 tests, re-run green here).

This landed in the mechanism-#3 gap-close pass (`.work/gap-close-ai-engine--3-multi-agent-orchestrator-report.md`).
Building anything here would have been exactly the duplicate-mechanism mistake this pass is
supposed to avoid, so I built nothing and left `multi_agent.py` untouched. The audit's fix item 1
(`delegate_fanout`, a non-null `parallel_group` on FAILURE_RECOVERY) should be considered
**superseded**, not outstanding.

### Gap 4 (SSH first-connection human dependency) — deliberately not "fixed"

Agreed with the audit: this is a CLAUDE.md policy checkpoint, not a defect. Untouched.

### Gap 2 (loop has never run past ENV_CHECK) — not a code gap

`.dv-harness/state.json` really does show every stage but `ENV_CHECK` at `NOT_STARTED`. But that is
a statement about this repo's runtime history, not about a missing wire: this harness project has no
RTL tree, no VIP and no reachable LSF farm of its own, so `BUILD`/`VERIFY` cannot execute here at
all. Nothing in a code change closes that; it closes when the harness is pointed at a real project.
The audit's own verification method (item 3) already says as much — it asks for a run against "a
project with a deliberately-seeded failing testcase", which is a separate exercise, not a patch. I
did make the *stage-level* half of it provable without a farm: the new tests drive a real
`DVHarness.loop()` over the real shipped graph and the real `tools/` tree at `WAVE_ANALYSIS`.

### Gap 3 (waveform dump gate is a self-attested string) — REAL, and the one I closed

Confirmed by reading the code: `focused_wave_debug_window_gate.py` required
`dump_scope_confirmed.confirmed_by` to be a non-empty string and nothing more, while
`adapters/cli.py:153` really does dispatch `claude -p --output-format json --max-turns N
--dangerously-skip-permissions --agent <node.agent>` with the prompt piped once through stdin. So on
the autonomous path there is no channel by which a human could answer, and the only way past the
check was the LLM writing the field itself — **the gate passed precisely when nobody had been
asked**. This is the gap I fixed.

---

## What changed

Governing constraint throughout: wire the mechanisms that already exist, add no second one.

### 1. `dv_harness/waveform_dump_gate.py` (new, ~215 lines)

Owns the canonical waveform-dump-scope question and the verification of an answer to it. It composes
`question_queue` primitives; it defines no storage, no new decision format and no second notion of
"confirmed":

- `dump_scope_question_key(scope)` — derived through `question_queue.make_question_key()`, so the
  ask side and the verify side cannot drift on what "the same question" means. The **declared scope
  is the question's identity**: one confirmation never authorizes a wider dump.
- `ask_dump_scope_confirmation()` — files one question through the real `QuestionQueueStore`.
  `blast_radius="unbounded"`, which `classify_tier()` maps to Tier 3 (blocking, stays OPEN, no
  auto-answer). That is not a label picked to force an escalation: an unconfirmed dump scope's worst
  case genuinely is unbounded, which is Part B's own bar. Nothing in this module writes a decision.
- `verify_dump_scope_confirmation()` — requires (a) a decision for that scope's key, (b) its
  `current.source == question_queue.HUMAN_DECISION_SOURCE`, and (c) `confirmed_by` to name the human
  who actually decided it (`current.decided_by`, case-insensitive). Only
  `QuestionQueueStore.answer_question()` writes source `human_answer`, and only a human runs it.

(b) is the load-bearing reuse: it is the same single sanctioned source
`connectivity.enforce_bind_tier_policy()` and `connectivity.apply_answered_questions()` already use
for T3 binds and unfilled scoreboard fields, so the harness cannot satisfy its own waveform
escalation with its own earlier Tier-2 guess.

Four distinct failure reasons, because they have four different remedies:
`WAVEFORM_DUMP_SCOPE_NOT_ASKED` (file it) / `_AWAITING_ANSWER` (a human answers it) /
`_NOT_HUMAN_ANSWERED` (a Tier-2 auto-assumption is on file) / `_CONFIRMED_BY_MISMATCH`. A Tier-3
question writes no decision, so the first two can only be told apart by consulting the questions
store as well — which `verify` does.

### 2. `tools/verification_flow/focused_wave_debug_window_gate.py`

Imports `verify_dump_scope_confirmation` via the established `DV_HARNESS_PACKAGE_ROOT` +
`sys.path.insert` pattern already used by four sibling gate scripts, and runs it after the existing
shape checks. The question store is resolved from **cwd**, not the package root — `gates.run_gate()`
always invokes with `cwd=<project root>`, the same convention the governance-policy read above it
already used. The pre-existing shape failures gained `needs_user_input: True`.

Everything the gate already enforced is untouched and still enforced after a real confirmation
(window math, WAVE=1/FSDB_START=0, stop, kill, identity, evidence hash), and the
`deep_debug_required:false + reason` escape hatch is unaffected — it opens no dump, so it needs no
confirmation.

### 3. `dv_harness/gates.py` — the routing half

Extended the **existing** `NEEDS_USER_INPUT` mechanism (previously reachable only from INTAKE's
`intake_readiness`) to this gate's confirmation failures, scoped by gate id **and** the gate's own
explicit `needs_user_input` flag, so an unrelated failure of the same gate (bad FSDB window, missing
evidence hash) stays an ordinary retry-worthy `GATE_FAIL`. The reason set is imported from the module
that owns it rather than restated, so a renamed reason cannot silently stop matching.

This is what makes the fix bite: `run_stage()` already maps `NEEDS_USER_INPUT` to
`Status.WAIT_USER`, and `loop()` already returns on `WAIT_USER`. Without it, an unanswerable
question would burn `max_stage_retries` at a subprocess that cannot answer it and then take the
graph's FAIL edge with the question still open. `_waveform_dump_user_question()` renders the real
Q-ID and the real remedy command into `blocking_reason`.

### 4. `dv_harness/cli.py` — the ask half

`dv-harness waveform-dump-scope ask --scope <scope> --level-or-depth <level>` (files the Tier-3
question, prints the Q-ID) and `... status --scope <scope>` (same check the gate runs; exit 2 when
unconfirmed). Deliberately a thin front end onto `question-queue`: a human answers with the existing
`dv-harness question-queue answer <Q-ID>`. There is **no** separate "waveform confirm" verb, because
a second way to record a confirmation would be a second thing the gate has to trust.

### 5. `dv_harness/prompts.py`, `dv_harness/engine.py`, `CLAUDE.md`

Both stage instruction blocks (WAVE_ANALYSIS and FAILURE_RECOVERY) now tell the agent the real
3-step protocol and that `confirmed_by` must name the human who answered the Q-ID — plus that a
WAIT_USER stop here is expected and must not be worked around by rewriting evidence. One stale
comment in `engine.py` ("today, only INTAKE's intake_readiness gate produces this") corrected.
CLAUDE.md's Waveform Dump User Gate section records the enforcement and its disclosed residual.

---

## Verification

New: `dv_harness_tests/test_waveform_dump_scope_human_confirmation.py` — 8 tests, real gate
subprocess, real `QuestionQueueStore` on disk, real shipped graph, real `tools/` tree. No mocked
store, no hand-built `decisions.json`.

The two that prove the **wiring** (the actual gap — the underlying function working was never in
question):

- `test_unconfirmed_dump_scope_stops_the_real_loop_at_wait_user_without_retrying` — a real
  `DVHarness.loop()` at `WAVE_ANALYSIS` with an adapter emitting a self-attested `confirmed_by`
  (the best a headless subprocess can do) parks at `Status.WAIT_USER` with the real Q-ID and the
  `waveform-dump-scope ask` command in `blocking_reason`, after **exactly one** dispatch, still on
  `WAVE_ANALYSIS`. The retry-count assertion is the half a plain `GATE_FAIL` would have got wrong.
- `test_loop_gets_past_the_gate_once_a_real_human_answers` — the same project, one real
  `answer_question()` in between, reaches `Status.PASS`. The stop is a resumable checkpoint, not a
  dead end.

The rest: self-attested string rejected; filed-but-unanswered distinguished from never-asked; a
harness-minted Tier-2 auto-assumption rejected; false attribution rejected; a wider scope rejected;
window/kill rules still enforced after a real confirmation; and the `gates.py` verdict routing in
isolation, including that an unrelated failure of the same gate stays `GATE_FAIL`.

Rewritten (they asserted the old, weaker contract and correctly went red):
`test_wave_analysis_requires_confirmed_dump_scope` — its `confirmed_by: "user"` case used to PASS
and now must not; `test_failure_recovery_requires_focused_wave_debug_window_gate` — its bad-window
payload now stops at the confirmation check first, so the window rule it was proving is proven in
the new file against a seeded store on the same script.

Suites run, all exit 0:

| suite | result |
|---|---|
| `test_engine_gates_and_routing.py` | 239 passed (16m31s) |
| `test_hard_gate_script_smoke.py` + `test_four_key_judgments_enforcement.py` + `test_rca_multi_agent_fanout.py` + `test_qualified_conclusion.py` | 244 passed |
| `test_question_queue.py` + `test_cli_question_queue.py` + `test_blackboard_subsystem_wiring.py` + `test_bind_mechanism_generator.py` + `test_source_authority.py` | 130 passed |
| `test_waveform_dump_scope_human_confirmation.py` (new) | 8 passed |

CLI smoke-tested for real against a throwaway project root: `ask` files `Q-ENV-55C52081` at tier 3,
`blocking: true`, `status: OPEN`; `status` then exits 2 with `WAVEFORM_DUMP_SCOPE_AWAITING_ANSWER`.

## Concurrent-tree handling

`dv_harness/engine.py` was concurrently modified by another workstream (a `memory_context` /
`build_memory_context_references` change). I hand-scoped the commit: extracted only my own hunk into
a patch and `git apply --cached` it, leaving their two hunks unstaged in the working tree. All other
files I touched were verified hunk-by-hunk as entirely mine before staging.

## What remains open (not attempted here, correctly)

- **A real end-to-end `dv-harness loop` against a project with a seeded failing testcase.** Needs a
  real RTL tree, VIP and farm; this repo has none. This is the audit's verification item 3 and is a
  separate exercise, not a patch.
- **The general "a headless autonomous run cannot ask a human anything mid-flight" limitation.**
  This change closes it for the waveform decision specifically, by parking at WAIT_USER with a real
  Q-ID. A general in-flight ask channel for headless subprocesses would be its own design effort.
