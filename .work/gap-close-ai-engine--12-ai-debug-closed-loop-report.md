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
