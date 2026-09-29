# Gap-close pass: AI mechanism #5 — Plan-and-Execute / ReAct Engine

**Status: NO_ACTION_NEEDED**

No file was modified. No commit was made.

Date: 2026-09-04 (re-verification pass over the fresh re-audit)

> The previous revision of this file, written by the 2026-09-04 03:22 gap-close
> that produced commit `c2d6efd`, is preserved in git history. This revision
> records today's independent *re-verification* of that fix, which is what this
> pass was asked to do.

---

## What I did

The fresh audit returned **WIRED_AND_FIRING** with no gap named. Per the task's
rule 1, that means: touch no code, but independently re-confirm the cited
evidence against the *current working tree* rather than trusting the audit text,
and re-run the tests myself.

---

## Re-verification results

### 1. The commit is real and in history

`git log --oneline -- dv_harness/react_loop.py dv_harness/react.py dv_harness/engine.py`:

```
...
c2d6efd ReAct engine: give the inner loop a real action space and the step record real inference
...
```

`c2d6efd` exists in real history — not aspirational, not a report-only claim.

### 2. Concurrency check (task rule 4) — done BEFORE reading for content

| File | `git status` | Consequence |
|---|---|---|
| `dv_harness/react_loop.py` | **clean** | audit's line numbers still valid |
| `dv_harness/react.py` | **clean** | audit's line numbers still valid |
| `dv_harness/inference.py` | **clean** | scoring primitives untouched |
| `dv_harness_tests/test_react_inference_wiring.py` | **clean** | tests are the committed ones |
| `dv_harness/engine.py` | **modified** (+167/-7, concurrent workstreams) | line numbers shifted — re-located by content |

`git diff -U0 dv_harness/engine.py | grep -i react` returns **only two comment
lines** (both merely *mentioning* `InnerReactLoop` in prose added by another
workstream). The uncommitted hunks sit at new-file lines 160, 1014, 1071, 1121,
1876, 1993, 3154, 3400, 3416, 3673 — none of them inside
`_react_step_inference()` or inside the `if node is not None:` ReAct record
block. **The concurrent edits did not touch this mechanism's code path.**

Because engine.py moved, I re-located the audit's call sites by content:

| Audit's cited location | Actual current location | Status |
|---|---|---|
| `engine.py:1336` `_react_step_inference()` | `engine.py:1392` | present, intact |
| `engine.py:3489-3538` call inside `run_stage()` | `engine.py:3560-3572` | present, intact |
| `react_loop.py:273-307` `build_menu()` source #5 | `react_loop.py:273-307` | present, clean |
| `react.py:145-178` WM persistence | `react.py:138-171` | present, clean |

### 3. The stale "prior audit" artifacts are exactly as described

`ls --time-style=long-iso` over the on-disk artifacts: **every**
`WM-REACT-*.json` (13 files) and **every** `reflect_*.json` (3 files) is dated
**2026-09-01**, i.e. all predate the 2026-09-04 fix. I read two of them:

`.dv-harness/react/DISCOVERY/attempt_001/reflect_001.json` — both signatures are
the degenerate `{"status":"FAIL","reason":"NO_EVIDENCE_BLOCK_SUPPLIED"}` shape,
and the menu is a **1-option `CONVERGE_TERMINATE`** list.

`.dv-harness/memory/working/WM-REACT-DISCOVERY-001.json` — **no `gap` key at
all**, `"confidence": "MEDIUM"` as a bare literal, `"next_action":
"retry_or_reroute"` (the old hardcoded string map), `hypothesis` a RouteResolver
sentence.

So the prior audit's PARTIALLY_WIRED reading was correct *for these artifacts*,
and today's different verdict rests on a dated code change, not a re-reading —
confirmed first-hand.

### 4. The fix does what the audit says, read directly from source

- **`react_loop.py` source #5** (`build_menu`, lines 273-307): guarded by
  `if sig.gate_id in missing_evidence_blocks:`, where `missing_evidence_blocks
  = identify_gap(all_gate_ids, supplied_gate_ids)` (line 207) — a real set
  difference over the stage's real configured gate list, not a hand-rolled
  check. It emits `REQUEST_EVIDENCE:<gate_id>:evidence_block` with source
  `stage_gate_missing_evidence_block`, optionally citing a real
  `protocol_builder_registry` item via `next_best_action()`. This is precisely
  the case sources 1-4 could not reach (they all need the failing gate's own
  detail to already enumerate what is missing; a gate that never ran cannot).
- **`engine.py:1392` `_react_step_inference()`**: computes `required` from
  `effective_stage_gates(stage, self.root)`, `gap = identify_gap(...)`,
  `counter_evidence_count` from really-failing gate signatures, and derives
  `next_action` from a real reroute target / `next_best_action()` / real failing
  gate ids. Called at `engine.py:3568` inside `run_stage()`.
- **`react.py:138-171`**: `record()` persists `gap` / `confidence_detail` /
  `memory_context` into both `iteration_NNN.json` and the
  `kind: "react_reasoning_step"` `WM-REACT-<node>-<iter>.json`.
- **`inference.py:58` `score_confidence()`**: `level = HIGH if base >= 6 else
  MEDIUM if base >= 3 else LOW`, which is exactly what the tests' literal
  `1*2 - 2*3` (= -4, LOW) and `3*2 - 1*3` (= 3, MEDIUM) assertions encode.

### 5. Wiring is unconditional — no bypass, verified against the real graph

`dv_harness/graph.py:52` — `react: bool = True` is the dataclass default.
I parsed the real `.dv-harness/graph/main_graph.json` myself:

```
total nodes: 41
nodes with react=False: []
nodes explicitly setting react: []
```

So no node in the real graph opts out, and `if node is not None:` is the only
guard. `test_graph_node_react_default_and_policy_default_keep_this_wiring_live`
(`test_react_inference_wiring.py:376`) is a standing regression guard on exactly
this.

### 6. The tests really assert on the production path, not on functions in isolation

This was the crux of the original gap, so I read the test file rather than
trusting its name. `_mk_smoke_project()` copies the **real** `main_graph.json`,
the **real** `.claude/agents`, and the **real** `tools/` tree (so the gate
scripts genuinely subprocess-run). The engine-driven tests then construct a real
`DVHarness(tmp)`, swap in only the LLM adapter, and call
`h.run_stage("calibrate architecture")` — after which they assert on the files
`run_stage()` itself wrote:

- `.dv-harness/react/ARCH_CALIBRATION/attempt_001/reflect_001.json`:
  `len(menu) > 1`, `chosen_option_id.startswith("REQUEST_EVIDENCE:")`,
  `converged is False`, chosen option's `source ==
  "stage_gate_missing_evidence_block"`, and the targeted re-attempt prompt
  really naming the target.
- `WM-REACT-ARCH_CALIBRATION-001.json`: `gap` equals the real
  `identify_gap()` output, `confidence_detail["score"] == 1*2 - 2*3`,
  `next_action` equals the real `next_best_action()` suggestion and explicitly
  `!= "retry_or_reroute"`.
- A contrast case (`..._confidence_really_tracks_the_evidence_not_the_status`)
  drives a run with the **same** `PARTIAL` status but full evidence and asserts
  a **different** real score (`3*2 - 1*3`, MEDIUM) and
  `next_action == "reroute:ARCH_DISCOVERY"` — proving the number is
  evidence-driven, not status-driven.

The fake adapter is genuinely falsifiable rather than cooperative: it picks
whatever `REQUEST_EVIDENCE` option the **real** menu offers, so if `build_menu()`
regressed to a CONVERGE-only menu the adapter could not select one and the test
would fail.

### 7. Tests re-run by me, against today's tree

I did not trust the audit's quoted run. I re-ran all three react suites myself,
against the current tree *including* the concurrent uncommitted `engine.py`
changes:

```
$ python -m pytest dv_harness_tests/test_react_inference_wiring.py \
                   dv_harness_tests/test_react_loop.py \
                   dv_harness_tests/test_react_working_memory_bridge.py -q
36 passed in 306.30s (0:05:06)
```

(11 `test_react_inference_wiring` + 21 `test_react_loop` + 4
`test_react_working_memory_bridge`; exit code 0.) The concurrent engine.py
edits have not broken this mechanism.

---

## Why no fix

The audit named no gap, and every artifact it cited checks out first-hand
against the current tree, including under the concurrent uncommitted `engine.py`
edits. There is nothing to wire — the mechanism is already wired into
`DVHarness.run_stage()` unconditionally, and the tests that prove it assert on
the real persisted files rather than on `inference.py` in isolation, which is
exactly the distinction the original gap turned on.

Per task rule 2's guidance about not reinventing an existing mechanism: building
anything here would have duplicated a working path.

---

## Disclosed residual (not a gap, no code change would close it)

No production run of this harness has occurred since the fix landed at 03:22 on
2026-09-04 — I re-confirmed by timestamp that no `WM-REACT-*.json` or
`reflect_*.json` on disk postdates it. So there is still no *end-user-session*
post-fix record, only test-harness ones.

I deliberately did **not** manufacture one. Driving a real stage through this
repo's live `.dv-harness/` would mutate `state.json` and `events.jsonl`, both of
which are currently dirty from other concurrent workstreams in this same
session — writing a production artifact purely to satisfy an audit would risk
corrupting that concurrent work, and a run staged solely for the audit is not
meaningfully more "real" than the test-harness run that already exercises the
identical code path end to end.

**How a future audit gets a genuinely fresh production artifact:** run any real
stage through `DVHarness.run_stage()` on a live DV project and inspect the new
`WM-REACT-*.json` it writes. No code change is required.
