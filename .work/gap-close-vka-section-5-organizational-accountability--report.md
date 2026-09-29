# Gap-close pass — VKA Section 5: Organizational (accountability, trust progression, knowledge asymmetry)

Date: 2026-09-04. Scope: Section 5 only.

**Line-number drift warning.** CLAUDE.md is being edited concurrently by other active workflows,
so section offsets move between passes. Anchor by heading text, not by line number:
- incoming audit cited `CLAUDE.md:493-536`
- the previous pass of this report re-resolved them to `526-570`
- **this pass re-resolved them to `617-660`** (verified via
  `grep -n "Agent-Authored Change Accountability\|Trust Progression for Autonomous" CLAUDE.md`
  → 617, 641; `wc -l CLAUDE.md` → 1167)

The three headings are `## Agent-Authored Change Accountability (2026-09-03)`,
`## Trust Progression for Autonomous/Semi-Autonomous Work (2026-09-03)`, and the
`**Deliberately preserved knowledge asymmetry**` paragraph that closes the latter.

## Result: **NO_ACTION_NEEDED** — no source file modified.

- 5a Accountability — **READY** (re-confirmed, now with live gate output)
- 5b Trust progression — **READY** (re-confirmed; its "not mechanically enforced" self-disclosure
  re-verified as accurate)
- 5c Knowledge asymmetry — **PARTIAL by design → NO_ACTION_NEEDED** (prose-only is the correct
  scoping; there is no real code seam to attach a mechanism to, see below)

This pass independently re-derived every verdict from the current tree rather than trusting the
previous pass's report; the load-bearing 5c claim was re-checked from scratch (see 5c.1).

---

## 5a — Accountability: READY (re-confirmed)

Policy text present verbatim, current line numbers:
- `CLAUDE.md:624-625` — "**The agent is a tool, not an accountable party.** Claude Code (or any
  automated caller) proposes; it never bears responsibility for a merged/pushed change's
  consequences."
- `CLAUDE.md:626-629` — "**The human approver of a PR/merge carries the same responsibility as if
  they had authored the change by hand.** ... the approver is the accountable party for any
  escape that change causes."
- `CLAUDE.md:630-634` — anchors the policy to the hard technical gate it depends on, and states
  that removing that gate would remove the policy's precondition.

The gate it depends on is real, wired, and **live on this machine** — not merely referenced:
- `dv_harness/git_governance.py` implements `evaluate_pre_push()` / `evaluate_pre_merge_commit()`.
- Real call sites: `tools/git-hooks/pre-push` and `tools/git-hooks/pre-merge-commit`, both
  invoking `python -m dv_harness.cli --project-root "$REPO_ROOT" git-guard --check <hook>`.
  A non-zero exit aborts the git operation per githooks(5); `pre-merge-commit` resolves the
  landing branch itself via `git rev-parse --abbrev-ref HEAD` because git does not pass it.
- The hooks are this repo's ACTIVE hook path, not dormant templates:
  `git config --get core.hooksPath` → `tools/git-hooks`.
- **Exercised for real this pass** (not just unit-tested):
  ```
  $ CLAUDE_CODE=1 CLAUDECODE=1 python -m dv_harness.cli --project-root . \
        git-guard --check pre-merge-commit --branch main
  { "hook": "pre-merge-commit", "allowed": false,
    "reason": "BLOCKED: AI-agent environment (markers: ['CLAUDECODE', 'CLAUDE_CODE',
               'CLAUDE_CODE_ENTRYPOINT', 'CLAUDE_CODE_SESSION_ID']) attempted a direct merge
               into protected branch 'main'. Open a PR instead (gh pr create) ...",
    "branch": "main", ... }
  EXIT=1
  ```
  Exit 1 is the value git acts on, so the human-decision-point precondition the accountability
  policy rests on is genuinely enforced today.
- Tests: `python -m pytest dv_harness_tests/test_git_governance.py -q` → **30 passed in 0.36s**.

Nothing to build. Verdict stands.

## 5b — Trust progression: READY (re-confirmed)

- `CLAUDE.md:645-647` — tier 1 = near-zero-risk tasks (log/failure triage, report generation,
  coverage summarization); "A wrong output here costs a few minutes of a human's attention, not
  a bad tapeout decision."
- `CLAUDE.md:648-650` — extend autonomy toward stimulus/pattern modification only after a tier-1
  track record, "the tier where a wrong output can silently produce a false PASS."
- `CLAUDE.md:651-653` — explicit self-disclosure that this is a recommended adoption ordering,
  "not a mechanically enforced gate in the engine."

I re-ran the check that makes that self-disclosure honest rather than an excuse:
`grep -rniE "trust[_ ]?progression|trust[_ ]?tier|autonomy[_ ]?level|stimulus.*modification"
dv_harness/ --include=*.py` → **zero hits**. There is no competing engine-side trust gate, so the
document neither overclaims enforcement nor under-describes an existing mechanism. The spec asks
for this ordering to be *stated* as a deliberate team decision; it is. Verdict stands.

## 5c — Knowledge asymmetry: NO_ACTION_NEEDED (prose-only is correct here)

`CLAUDE.md:655-660` states the principle and correctly scopes it as team practice: teams "should
deliberately route some fraction of real failures to a human for hands-on debug rather than
letting the harness resolve every one it technically could, treating this as an investment in the
team's future capability rather than lost efficiency today."

The incoming audit sketched a possible closure (a `human_debug_fraction` config knob wired into
`react_loop.py`/`degradation.py`) while itself concluding this was "flagged for visibility, not
as a defect requiring code." I re-checked from scratch whether that sketch is buildable as a REAL
mechanism rather than a synthetic hook, and it is not:

1. **There is no auto-triage seam to sample.** Re-verified this pass:
   `grep -rnE "def .*triage|auto_triage|auto-resolve|auto_resolve" dv_harness/ --include=*.py`
   → **zero hits**. The harness has no function that autonomously resolves a failure.
   `react_loop.py` is a stage-level reflect/decide/act loop over an LLM adapter, and
   `sim_log_analysis.py` only parses/classifies log signatures — it produces evidence for a
   human/agent to read, it does not close out a failure. A `human_debug_fraction` knob would
   therefore gate nothing real: a config field plus a randomizer with no genuine "the harness
   would otherwise have resolved this" decision point to intercept. That is precisely the
   adjacent-sounding-but-fake asset this audit series exists to catch.

2. **The human-routing primitive the principle needs already exists — human-initiated.**
   `TAKEOVER` is real and is checked first by the engine (`dv_harness/control_plane.py:26` "the
   strongest override -- engine.py checks it first"; `DEFAULT_TAKEOVER` at `control_plane.py:36`,
   merged/validated at `control_plane.py:94-98`; CLI `takeover` / `release-takeover` in
   `dv_harness/cli.py`). A team practising the recommendation uses this today. What is absent is
   only an automatic sampler that withholds work from the harness on its own.

3. **The existing escalation path has the opposite trigger condition.** `question_queue.py`
   escalates on harness *uncertainty*: `is_cannot_assume()` at `question_queue.py:127-135` is
   "true iff `context` claims the question ... hard-coded per spec ('a hard-coded trigger, not a
   judgment call')", with `hard_triggers()` at `:180` and `classify_tier()` at `:193`. That fires
   when the harness does **not know** — not when it *could* resolve something but withholds it
   for training value. Different mechanism, not a partial version of this one.

4. **Near-miss names confirmed unrelated** (so the greps above are not missing a hidden
   implementation): `AsymmetryFinding` at `dv_harness/reference_pattern_audit.py:179-180` is
   explicitly "one flagged host/DUT write asymmetry: within a single file, one side ..." —
   register-write pattern auditing, not knowledge asymmetry. A direct search for a real
   mechanism, `grep -rniE "human_debug|debug_fraction|training_queue|learning_queue|
   sampling_fraction|knowledge.?asymmetry" dv_harness/ --include=*.py`, returns **zero hits**.

Building the sampler would also be an unrequested, throughput-degrading default behavior change
on shared files (`config.py`, `react_loop.py`) that other workflows are concurrently editing, for
a principle the user framed as organizational adoption guidance.

Per the task's own scoping rule for this item ("do not force a code mechanism onto it if the
audit correctly found it's prose-only by design"), 5c is closed as NO_ACTION_NEEDED. The CLAUDE.md
text is accurate, honestly scoped, and does not claim enforcement it lacks.

## Tests

No source change was made, so no new tests were written. The suites backing the verdicts were
re-run as re-confirmation:
`python -m pytest dv_harness_tests/test_git_governance.py dv_harness_tests/test_question_queue.py -q`
→ **77 passed in 7.02s**.

## Files touched

Only this report. No file in `dv_harness/`, `tools/`, or `CLAUDE.md` was modified by this pass.
