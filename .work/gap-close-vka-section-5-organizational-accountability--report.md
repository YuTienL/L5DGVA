# Gap-close pass — VKA Section 5: Organizational (accountability, trust progression, knowledge asymmetry)

Date: 2026-09-04. Scope: Section 5 only. Audit-only inputs re-verified against the CURRENT
working tree (CLAUDE.md is concurrently modified by other workflows, so every line number
below was re-resolved just now, not copied from the incoming audit — the incoming audit's
`CLAUDE.md:493-536` citations have since shifted to `526-570`).

## Result: **NO_ACTION_NEEDED** — no file modified, no commit of code.

- 5a Accountability — **READY** (re-confirmed, evidence still live)
- 5b Trust progression — **READY** (re-confirmed, its "not mechanically enforced" self-disclosure
  re-verified as accurate)
- 5c Knowledge asymmetry — **PARTIAL by design → NO_ACTION_NEEDED** (prose-only is the correct
  scoping; there is no real code seam to attach a mechanism to, see below)

---

## 5a — Accountability: READY (re-confirmed)

Policy text, current line numbers:
- `CLAUDE.md:533` — "**The agent is a tool, not an accountable party.** Claude Code (or any
  automated caller) proposes; it never bears responsibility for a merged/pushed change's
  consequences."
- `CLAUDE.md:535` — "**The human approver of a PR/merge carries the same responsibility as if
  they had authored the change by hand.**"
- `CLAUDE.md:539` — anchors that policy to the hard technical gate it depends on.

The gate it depends on is real and live, not merely referenced:
- `dv_harness/git_governance.py:152` `evaluate_pre_push(stdin_text, env)`,
  `dv_harness/git_governance.py:183` `evaluate_pre_merge_commit(current_branch, env)`.
- Real call sites: `tools/git-hooks/pre-push` and `tools/git-hooks/pre-merge-commit:24`, both
  invoking `python -m dv_harness.cli --project-root "$REPO_ROOT" git-guard --check <hook>`;
  a non-zero exit aborts the git operation per githooks(5).
- The hooks are not just templates sitting in a directory — they are this repo's ACTIVE hook
  path: `git config --get core.hooksPath` → `tools/git-hooks` (rc=0). So the gate fires today,
  on this machine, with no remote or CI involved.
- Tests: `python -m pytest dv_harness_tests/test_git_governance.py -q` → **30 passed in 0.44s**.

Nothing to build. Verdict stands.

## 5b — Trust progression: READY (re-confirmed)

- `CLAUDE.md:554` tier 1 = near-zero-risk tasks (log/failure triage, report generation, coverage
  summarization); `CLAUDE.md:557` = extend autonomy toward stimulus/pattern modification only
  after a tier-1 track record; `CLAUDE.md:560` = explicit self-disclosure that this is a
  recommended adoption ordering, "not a mechanically enforced gate in the engine".

I re-ran the check that makes that self-disclosure honest rather than an excuse:
`grep -rn "trust.*tier|trust_progression|autonomy" dv_harness/ --include=*.py` → **zero hits**.
There is no competing/contradicting engine-side trust gate, so the document does not overclaim
and does not under-describe an existing mechanism. Verdict stands.

## 5c — Knowledge asymmetry: NO_ACTION_NEEDED (prose-only is correct here)

`CLAUDE.md:564` states the principle correctly and scopes it as team practice: teams "should
deliberately route some fraction of real failures to a human for hands-on debug rather than
letting the harness resolve every one it technically could."

The incoming audit sketched a possible closure (a `human_debug_fraction` config knob wired into
`react_loop.py`/`degradation.py`) while itself concluding this was "flagged for visibility, not
as a defect requiring code." I checked whether that sketch is actually buildable as a REAL
mechanism rather than a synthetic hook, and it is not:

1. **There is no auto-triage seam to sample.**
   `grep -rn "def .*triage|auto_triage|auto-resolve" dv_harness/ --include=*.py` → **zero hits**.
   The harness has no function that autonomously resolves a failure. `react_loop.py` (574 lines)
   is a stage-level reflect/decide/act loop over an LLM adapter (`InnerReactLoop.run` at
   `dv_harness/react_loop.py:477`), and `sim_log_analysis.py` only parses/classifies log
   signatures (`parse_sim_log:171`, `classify_signatures:252`) — it produces evidence for a
   human/agent to read, it does not close out a failure. A `human_debug_fraction` knob would
   therefore gate nothing real: it would be a config field plus a randomizer with no genuine
   "the harness would otherwise have resolved this" decision point to intercept. That is exactly
   the adjacent-sounding-but-fake asset this audit series exists to catch.

2. **The human-routing primitive the principle needs already exists — human-initiated.**
   `TAKEOVER` is real and is checked first by the engine (`dv_harness/control_plane.py:26,36`;
   CLI `dv-harness takeover` / `release-takeover` at `dv_harness/cli.py:156,159`, applied via
   `dv_harness/commands.py:46`). A team practising the recommendation uses this today. What is
   absent is only an automatic sampler that withholds work from the harness on its own.

3. **Building that sampler would be an unrequested, throughput-degrading behavior change.**
   `question_queue.py`'s existing escalation triggers on harness *uncertainty*
   (`is_cannot_assume:113`, `hard_triggers:150`, `classify_tier:163`) — a fundamentally different
   trigger condition. Adding a "deliberately stop short on N% of work the harness could handle"
   path would change default engine behavior on shared files (`config.py`, `react_loop.py`)
   that three other workflows are concurrently editing, for a principle the user framed as
   organizational adoption guidance.

Per the task's own scoping rule for this item ("do not force a code mechanism onto it if the
audit correctly found it's prose-only by design"), 5c is closed as NO_ACTION_NEEDED. The
CLAUDE.md text is accurate, honestly scoped, and does not claim enforcement it lacks.

## Tests

No change made, so no new tests were written. The one suite backing the 5a verdict was re-run
as re-confirmation: `python -m pytest dv_harness_tests/test_git_governance.py -q` → 30 passed
in 0.44s.

## Files touched

Only this report. No source file in `dv_harness/`, `tools/`, or `CLAUDE.md` was modified by
this pass.
