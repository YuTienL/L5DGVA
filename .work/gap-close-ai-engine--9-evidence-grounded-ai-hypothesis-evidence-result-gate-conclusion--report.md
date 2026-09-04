# Gap close — AI mechanism #9: Evidence-Grounded AI (Hypothesis + Evidence + Result + Gate = Conclusion)

**Status: DONE**

Date: 2026-09-04. Branch: `gap-close/env-manifest-fact-sources`.

## What I re-verified first (and where I diverged from the audit's plan)

The incoming audit's verdict (PARTIALLY_WIRED) was right about the *mechanism*
being real, and right that `RE_AUDIT` / `SIGNOFF` have **zero rows** in this
repo's own `.dv-harness/self_tuning/gate_history.jsonl`. I re-ran that diff
myself: the log has since grown from the audit's 24,150 rows to **41,277**, and
both stages are still absent from it.

But the audit's proposed fix — "drive `loop()` end to end so those two stages
appear in `gate_history.jsonl`" — is not a fix I was willing to make. That file
is the *real production history* of this repo. Driving a scripted adapter
through it would write synthetic rows into a real audit trail purely to make a
coverage query come out differently. That is the fabricated-evidence failure
`CLAUDE.md`'s own Evidence Truth Rule forbids, and it would close nothing.

The audit also asserted "no code change is required". That turned out to be
wrong, and re-reading the code is what showed it:

- The per-stage half of the audit's concern was **already closed**, in two
  places the audit did not account for. `dv_harness_tests/test_inference_engine_wiring.py:226`
  already drives a genuine `run_stage("RE_AUDIT")` PASS with all **11 real gate
  scripts executed as subprocesses**; `dv_harness_tests/test_signoff_stage_gate_e2e.py`
  (commit `07f84be`, the immediately preceding gap-close pass for mechanism #8)
  does the same for all **9 real SIGNOFF gates**. Those stages are absent from
  *this repo's* `gate_history.jsonl` only because e2e tests correctly run in
  throwaway project roots.
- What was **not** closed — and what actually is mechanism #9's own gap — is the
  last link in its name: the **Conclusion never entered closure.**

## The real gap (confirmed by execution, not by reading)

`engine.DVHarness._score_root_cause_confidence()` (`dv_harness/engine.py:1509-1511`)
composes, on every gate-verified RE_AUDIT/RCA_JOIN PASS, a real
`QualifiedConclusion` (`dv_harness/qualified_conclusion.py`) out of the stage's
hard-gate verdict **and** `inference.score_confidence()`'s independently
recomputed confidence, and writes it to the `qualified_conclusion` Blackboard
topic.

Nothing on the production path read it.

- A repo-wide grep for `qualified_conclusion` outside `.work/` matched only the
  writer (`engine.py`), the type (`qualified_conclusion.py`), `dashboard.py`
  (**display only**), and its unit tests.
- **No node** in the real shipped `.dv-harness/graph/main_graph.json` declared
  it in `blackboard_read`, so it never reached any stage's prompt.
  (`engine.py:2466` is where `node.blackboard_read` becomes the prompt snapshot;
  a topic no node declares is invisible to every agent.)
- `policy.can_signoff()` — the hard-stop `engine.loop()` consults at
  `engine.py:3890` **before** running SIGNOFF — asked only whether RE_AUDIT
  reached stage PASS (`require_second_pass_audit`). It never asked what RE_AUDIT
  *concluded*.

Those are different facts, and the difference is **reachable, not theoretical**.
`tools/verification_flow/root_cause_evidence_gate.py:134` mandates non-empty
`counter_evidence` only at its own HIGH/CONFIRMED tier. So a MEDIUM-confidence
finding with one supporting citation and two unrefuted counter-evidence entries
clears all 11 RE_AUDIT gates while `score_confidence()` recomputes to LOW
(`min(1,3)*2 + 2 - 2*3 = -2`), i.e. `is_qualified: false`.

I reproduced exactly that against the real gate scripts before touching
anything:

```
RE_AUDIT status: PASS
qualified_conclusion: {"gate_verdict": "PASS",
                       "inference_confidence": {"level": "LOW", "score": -2,
                                                "capped_by_counter_evidence": false},
                       "is_qualified": false}
can_signoff: (True, '', None)      <-- SIGNOFF allowed to proceed
```

A run whose own composed conclusion says "not qualified" closed into SIGNOFF
exactly like a fully qualified one.

## What changed

No new mechanism was built. The **existing** `QualifiedConclusion` was wired
into the **existing** production hard-stop and the **existing** graph.

1. **`dv_harness/policy.py`** — `can_signoff()` gains an optional `blackboard`
   argument (default `None`, so every existing caller/test is unchanged) and a
   new `require_qualified_conclusion` check: a recorded conclusion whose
   `is_qualified` is `False` refuses SIGNOFF. `redirect_stage` is `None`
   (BLOCKED, wait for a human) — matching its sibling `require_second_pass_audit`
   rather than the SHA-drift/open-findings auto-redirects, because a conclusion
   that did not qualify needs better evidence, which is a judgment, not a
   mechanical resync. Added `read_qualified_conclusion()` + the
   `QUALIFIED_CONCLUSION_TOPIC` constant so no caller re-implements Blackboard's
   `{"value": ...}` unwrapping; it never raises.
2. **`dv_harness/engine.py`** — `loop()`'s single `can_signoff()` call site now
   passes `self.blackboard`. This is the one production caller, so this line is
   what makes the check fire on the real path rather than only when a test
   opts in.
3. **`dv_harness/config.py`** — `policy.require_qualified_conclusion: True`
   added to `DEFAULT_CONFIG`, with a comment distinguishing it from
   `require_second_pass_audit`.
4. **`.dv-harness/graph/main_graph.json`** — `qualified_conclusion` added to
   `blackboard_read` on `REQUIREMENT_CLOSURE`, `PROMOTION_READINESS` and
   `SIGNOFF`, plus a `blackboard_key` entry on SIGNOFF's `expected_evidence`
   checklist. This is the other half of the edge: the refusal stops an
   unqualified conclusion from closing; this puts the conclusion in front of the
   closure stages at all. (Only one copy of this file exists in the tree.)
5. **`CLAUDE.md`** — a scoped addition to the existing "Blackboard Topics Written
   Outside the Graph" section, which this is a fourth instance of (approached
   from the opposite direction: written on the real path, read by nothing).

### Disclosed residual

Only a record that **exists and says `is_qualified: false`** refuses. Absence is
not a refusal — `require_second_pass_audit` already covers "RE_AUDIT never
passed", and blocking on absence would make every pre-existing project whose
RE_AUDIT status was set by any other route unclosable. This is scoped
deliberately, the same way `CLAUDE.md`'s Bind-Location Rules scope
`enforce_bind_tier_policy()`'s `require_tier` residual: what is closed hard is
the dangerous case. It is asserted as a test, not left implicit.

## Tests

New: `dv_harness_tests/test_qualified_conclusion_closure_gate.py` (8 tests). Its
RE_AUDIT gate fixtures are **imported** from `test_inference_engine_wiring.py`
rather than copied, so they cannot drift from the real gate scripts.

- `test_a_gate_passing_re_audit_can_still_conclude_not_qualified` — the
  reachability proof: all 11 real gate subprocesses PASS, stage closes PASS, and
  the conclusion is nonetheless `is_qualified: false` at LOW/score -2. Without
  this, the new check would guard an impossible state.
- `test_loop_refuses_signoff_while_the_recorded_conclusion_is_not_qualified` —
  the gap closed on the **real** path: `engine.loop()` must not dispatch SIGNOFF
  at all, proven by the SIGNOFF adapter recording **zero** calls, plus a
  built-in differential (`can_signoff` without the blackboard still returns
  `True`, i.e. the pre-fix behaviour; with it, `False`).
- `test_loop_reaches_signoff_once_the_conclusion_qualifies` — the same project,
  genuinely re-audited with the HIGH-confidence evidence, does dispatch SIGNOFF:
  the refusal is tied to the conclusion, not to anything else.
- `test_the_conclusion_topic_really_reaches_a_closure_stage_prompt` — the graph
  declaration is only half an edge; this asserts the engine really serializes the
  conclusion's own selected hypothesis into a real closure-stage prompt.
- `test_closure_nodes_read_the_conclusion_in_the_real_shipped_graph`,
  `test_absence_of_a_conclusion_record_is_not_a_refusal`,
  `test_require_qualified_conclusion_false_disables_the_check`,
  `test_read_qualified_conclusion_tolerates_missing_and_malformed_records`.

### Results

| run | result |
|---|---|
| `test_qualified_conclusion_closure_gate.py` (new) | **8 passed** |
| `test_engine_gates_and_routing.py` + `test_blackboard_subsystem_wiring.py` + `test_stage_evidence_checklists.py` | **273 passed** |
| `test_dashboard_interactive.py` + `test_graph_parallel_dispatch.py` + `test_emmc_cmdq_generator.py` (the `loop()`- and graph-driving files) | **80 passed** |

The whole-suite run overlapped a second concurrent pytest process and a second
workstream's in-flight edits, so its failures were triaged individually rather
than taken at face value. **None are attributable to this change:**

- `test_doc_citation_check.py` (2) — `docs/MEMORY_ARCHITECTURE.md` and
  `docs/MEMORY_SCHEMA.md` cite `dv_harness/memory.py` line numbers that moved.
  All three files belong to the concurrent memory workstream's uncommitted
  changes (visible in `git diff --stat`); none is touched here.
- `test_cli_pueue.py` (5) — `pueued` is not running on this machine, a
  pre-existing environmental failure already recorded in commit `fa101db`.
- The timing-sensitive `test_dashboard_interactive` / `test_graph_parallel_dispatch`
  positions re-run clean in isolation (the 80-test row above); they failed only
  while two pytest processes contended for the machine.

## Commit — and one honest note about how it landed

All seven files are committed and intact in `e29725f`:

```
dv_harness/policy.py                                     | 72 +++-
dv_harness/engine.py                                     |  7 +-
dv_harness/config.py                                     |  5 +
.dv-harness/graph/main_graph.json                        |  9 +-
dv_harness_tests/test_qualified_conclusion_closure_gate.py | 344 +++++
CLAUDE.md                                                | 26 ++
.work/gap-close-ai-engine--9-...-report.md               | 188 +++
```

`git diff HEAD` over those paths is empty, `HEAD:dv_harness/policy.py` contains
`require_qualified_conclusion`, and `HEAD:.dv-harness/graph/main_graph.json`
contains 4 occurrences of `qualified_conclusion`.

**But they landed under someone else's commit message.** This branch is being
worked concurrently. I staged exactly my seven paths and then ran `git commit`;
in the window between those two commands the concurrent memory workstream ran
its own `git commit`, which swept my staged index into `e29725f`
("docs: Phase 7 memory-note-schema gap-close report (DONE)"). My own commit then
correctly reported "no changes added to commit".

I deliberately did **not** amend or rebase to correct this. Another agent is
actively working on this branch and may already reference `e29725f`; rewriting
it to fix a commit message would risk real in-flight work to fix a cosmetic
problem. The code, tests and history are all correct — only the message
attribution is wrong, and this paragraph is the record of it. If the branch is
later cleaned up, the intended message was:

> `policy: refuse SIGNOFF while RE_AUDIT's Qualified Conclusion did not qualify`

## What is explicitly NOT claimed

`RE_AUDIT` and `SIGNOFF` still have zero rows in this repo's own
`gate_history.jsonl`, and this pass deliberately did not change that — see the
first section. Both stages' gate batteries are proven to execute for real, in
real throwaway project roots, by the e2e tests named above. "This harness repo
has never itself been driven through a full production DV pipeline" remains
true, is an honest statement about this repo, and is not something a fix pass
can or should manufacture.
