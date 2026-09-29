# Gap Close — Governance Layer: gh/git PR Gate + Audit

**Status: DONE**

**Test summary:** `python -m pytest dv_harness_tests/test_git_governance.py dv_harness_tests/test_cli_git_guard.py dv_harness_tests/test_git_hooks_e2e.py -q` → **47 passed** (39 pre-existing + 8 new end-to-end).

---

## 1. Re-verification first: the audit's own evidence had already moved again

I re-checked every cited fact before touching anything. Two of the audit's
premises were **already stale by the time I ran** (this box's state has now
changed twice in two days):

| Claim | Audit said (2026-09-03) | Reality when I checked (2026-09-04) |
|---|---|---|
| `core.hooksPath` | `tools/git-hooks` (installed; CLAUDE.md stale) | **Confirmed** — `tools/git-hooks` |
| GitHub remote | "`git remote -v` is empty" | **NO LONGER TRUE** — `origin https://github.com/YuTienL/DV_Agent_Harness.git`, reachable (`git ls-remote origin` exits 0) but **empty** (returns zero refs; `master` has no upstream) |
| `gh` on PATH | not on PATH | **Confirmed** — `command -v gh` finds nothing; `gh.exe` v2.99.0 only at `C:\Program Files\GitHub CLI\gh.exe` |
| `GIT_GUARD_DECISION` count | 3 | **Confirmed** — 3 |

The remote appearing is materially important: on 2026-09-03 a `git push`
died at `fatal: No configured push destination.` *before* hooks could run.
Today a `git push origin master` is a real, reachable operation — so the
local hook gate is now genuinely the only thing standing between an agent
and a direct write to `master` (the empty remote cannot carry a
branch-protection rule, since it has no branches).

## 2. The real gap I closed

The audit named a **doc gap** (stale self-disclosure) and flagged the
"organic firing" gap as optional. I closed both, because the second one is
the actual architectural claim:

**Nothing in the repo proved the edge the diagram draws.** `test_git_governance.py`
tests the decision function; `test_cli_git_guard.py` tests
`python -m dv_harness.cli git-guard` as a subprocess. Both prove the pieces
work *when something calls them*. **Neither ever ran a real `git push` or
`git merge`**, so the link `git's own hook runner → tools/git-hooks/* →
git-guard → abort the operation → events.jsonl → dv-harness audit` was
entirely untested — and every `GIT_GUARD_DECISION` in this repo's trail had
been produced by hand-invoking the hook script or the CLI, never by git.

### Fix A — new end-to-end test proving git itself fires the gate

`dv_harness_tests/test_git_hooks_e2e.py` (new, 8 tests). Each test builds a
throwaway repo whose `core.hooksPath` points at **this repo's real
`tools/git-hooks/` scripts** (not copies) plus a throwaway **local bare**
remote — never the network `origin`, never this repo. Agent markers are
passed to the child `git` process via the real `env=` kwarg and explicitly
*stripped* for the human cases (the test runner is itself an agent env).

Proven organically:
- real `git push origin master` with an agent marker → **git aborts**, output carries `BLOCKED` / `pre-push` / `protected branch 'master'`, and the bare remote still has **zero refs**;
- that blocked push writes exactly one real `GIT_GUARD_DECISION` (`hook=pre-push`, `allowed=false`, `branch=master`, `detected_markers` includes `CLAUDECODE`);
- that event is readable back through a real `python -m dv_harness.cli audit` run — closing the full diagram edge to `audit-change-governance-agent`'s evidence source;
- real `git push` with **no** agent marker → **succeeds** (the gate is not blanket local branch protection);
- real agent push to `feat/...` → **succeeds** (policy is "an agent may branch/commit/open a PR");
- real `git merge --no-ff feat/... ` onto `master` with an agent marker → **git aborts**, `master`'s HEAD does not move, one `pre-merge-commit` guard event;
- plus two regression guards asserting **this repo's own** `core.hooksPath` is still set and both hook scripts exist — so the "INSTALLED AND LIVE" doc claim can never silently rot again (which is exactly what happened last time).

No production code needed changing: the mechanism was correct, the
*connection* was simply unproven. That is why this is a wiring/coverage
fix, not a new parallel mechanism.

### Fix B — the stale self-disclosure, in all three places that carried it

The false "no remote / NOT YET INSTALLED" text existed in three documents,
not one. All corrected with dated, re-verified facts:

- `CLAUDE.md` — "gh CLI + PR-Only Governance Policy" section: replaced the
  2026-09-03 state paragraph and enforcement item 2. Now records the remote
  exists-but-is-empty, hooks are installed and live (activated *after* the
  original build report was written), the `gh`-on-PATH claim was false, and
  layer 1 (server-side protection) remains aspirational with a trigger for
  when to set it up.
- `tools/git-hooks/README.md` — same correction at the source the install
  instructions live at.
- `.claude/agents/audit-change-governance-agent.md` — this one mattered
  most: the audit agent was being *told* there is no remote. It now states
  the real state, plus the honest caveat that every `GIT_GUARD_DECISION` in
  this repo's own trail so far came from direct invocation rather than an
  organic incident.
- `dv_harness/git_governance.py` — one stale module comment asserting the
  remote is empty; corrected (comment only, no logic change).

## 3. Final verdicts for the box

- **gh/git PR Gate — local hook layer: REAL_AND_CONNECTED**, and now proven
  connected by git itself, not just by hand-invocation.
- **gh/git PR Gate — server-side GitHub branch protection: still
  ASPIRATIONAL**, and deliberately not attempted. A remote now exists but is
  empty; protecting a branch that does not exist yet, on an account I would
  have to authenticate, is an environment/account decision, per the task's
  own out-of-scope rule.
- **Audit (GIT_GUARD_DECISION → events.jsonl → `dv-harness audit` →
  audit-change-governance-agent): REAL_AND_CONNECTED**, and the previously
  untested first hop of that chain is now covered.

## 4. Deliberately NOT done

- No branch protection configured on GitHub (account/env decision).
- No `gh` PATH repair (machine-level env change, outside a code fix — documented instead).
- No push to the real `origin`. Every push in these tests goes to a
  throwaway local bare repo under pytest's `tmp_path`.

## Files

- `D:\DV\Task\DV_Agent_Harness_L5\v50\dv_harness_tests\test_git_hooks_e2e.py` (new)
- `D:\DV\Task\DV_Agent_Harness_L5\v50\CLAUDE.md`
- `D:\DV\Task\DV_Agent_Harness_L5\v50\tools\git-hooks\README.md`
- `D:\DV\Task\DV_Agent_Harness_L5\v50\.claude\agents\audit-change-governance-agent.md`
- `D:\DV\Task\DV_Agent_Harness_L5\v50\dv_harness\git_governance.py` (comment only)
