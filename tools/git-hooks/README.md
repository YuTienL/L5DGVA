# tools/git-hooks/ -- gh CLI + PR-only governance gate

Real, callable enforcement point for this project's L5 governance policy
(2026-09-03): an AI agent (Claude Code or any other automated caller) may
`git branch` / `git commit` / open a PR (`gh pr create`), but must never
merge or push directly onto a **protected branch** (`main` or `master`).
Human review via PR is the only path onto those branches. A human running
the identical `git push`/`git merge` from their own interactive terminal is
never blocked by this gate.

## Real current state of this repo (re-checked 2026-09-04, be honest about it)

```
$ git config --get core.hooksPath
tools/git-hooks                     # <- these hooks ARE installed and live
$ git remote -v
origin  https://github.com/YuTienL/DV_Agent_Harness.git (fetch/push)
$ git ls-remote origin
(no output, exit 0)                 # <- remote exists and is reachable, but is EMPTY
$ git branch -a
* master
```

These hooks are **installed** (`core.hooksPath` was pointed here on
2026-09-03, after this file was first written -- the earlier "NOT YET
INSTALLED" wording here and in CLAUDE.md was stale and has been corrected).
A GitHub `origin` **now exists** but is still empty, so there are no remote
branches and therefore no server-side branch protection yet: layer 2 below
is currently the only gate actually standing between an agent and a direct
`git push origin master`. History to date is still direct commits to a
local `master`; there is no live PR workflow to point at yet.

The gate is proven end-to-end (real `git push` / real `git merge --no-ff`,
driven by git's own hook runner against these exact scripts) by
`dv_harness_tests/test_git_hooks_e2e.py`, which also asserts this repo's
`core.hooksPath` is still set so the claim above cannot go stale silently.

## Layered enforcement

1. **Primary (once a real GitHub remote exists): server-side branch
   protection.** Configure the `main`/`master` branch on GitHub to require
   a PR with review before merging, and disallow direct pushes. This is
   the real, authoritative gate -- it holds even if a client-side hook is
   missing, bypassed with `--no-verify`, or the repo is re-cloned without
   `core.hooksPath` set. Set this up on the remote once one exists (e.g.
   `gh api repos/<owner>/<repo>/branches/main/protection ...` or the GitHub
   UI's branch protection settings).
2. **Secondary (this directory): a local, defense-in-depth git hook.**
   Catches the case a client-side hook still helps with -- an agent
   (Claude Code or similar) running `git push`/`git merge` directly against
   `main`/`master` on a machine where no remote/branch-protection exists
   yet, or before it re-syncs. It detects "is this process running inside
   an AI-agent environment" using the same env-marker pattern
   `tools/remote/remote_relay.py`'s own Layer 2 guard already established
   for an analogous problem (see that module and
   `dv_harness/git_governance.py`'s module docstring) -- reused via direct
   import, not copy-pasted, so the two guards cannot silently drift apart.
   A hook is always bypassable locally (`--no-verify`, deleting the hook,
   not installing it) -- it is a safety rail against an agent's own
   default behavior, not a security boundary. That is exactly why layer 1
   is the real gate once a remote exists.

## What actually decides PASS/BLOCKED

`dv_harness/git_governance.py` -- pure, unit-tested functions
(`evaluate_pre_push`, `evaluate_pre_merge_commit`). Both hook scripts below
are thin shells that gather the real git-provided input (stdin refspecs for
pre-push; the current branch for pre-merge-commit, which git does not pass
to that hook) and hand it to `dv-harness git-guard`
(`dv_harness/cli.py`'s `git-guard` subcommand), which prints the JSON
decision and exits 0 (allowed) / 1 (blocked) -- the exit code is what
actually makes git abort the operation, per githooks(5).

Every decision that actually touched a protected branch (blocked-for-an-
agent, or allowed-for-a-human) is logged as a `GIT_GUARD_DECISION` event
into `.dv-harness/events.jsonl` -- the same append-only audit trail every
other "who changed what, when" view already reads (`dv-harness audit`,
the dashboard's Audit panel). See `.claude/agents/
audit-change-governance-agent.md` for the agent responsible for reading
this trail back.

## Install

Recommended -- one repo-local git config, both hooks active immediately,
no per-clone file copy:

```
git config core.hooksPath tools/git-hooks
```

Alternative -- classic per-clone `.git/hooks/` install (must be repeated
on every fresh clone/worktree, since `.git/hooks/` is never itself under
version control):

```
cp tools/git-hooks/pre-push .git/hooks/pre-push
cp tools/git-hooks/pre-merge-commit .git/hooks/pre-merge-commit
chmod +x .git/hooks/pre-push .git/hooks/pre-merge-commit
```

On Windows, both install paths work unchanged under Git for Windows (Git
Bash's `sh.exe` runs the `#!/bin/sh` hook scripts regardless of
`core.hooksPath` vs. `.git/hooks/`).

## Known trade-off: fails OPEN, by design

If `python`/`python3` is not on `PATH` when a hook fires, both scripts
print a warning to stderr and exit 0 (allow the operation) rather than
blocking a human's push/merge over an unrelated environment problem. This
is a deliberate choice for a *secondary*, defense-in-depth gate: the
primary gate (server-side branch protection, once a remote exists) does
not depend on any local Python install at all. Do not rely on this hook
alone as your only protection for a shared remote -- configure layer 1.

## Testing this gate

Never test by actually pushing/merging into a real branch. `dv_harness/
git_governance.py`'s functions are pure (env dict + stdin text/branch name
in, a `GuardDecision` out) -- see `dv_harness_tests/test_git_governance.py`
for real captured-shape pre-push stdin and simulated AI-agent env markers,
following the same "unit-test the pure function, never invoke the real
hook live" discipline `dv_harness_tests/test_remote_relay.py` already
established for `remote_relay.py`'s own Layer 2 guard.
