# gh CLI + PR-Only Governance Policy + Audit/Change Governance Agent

2026-09-03. Scope: install `gh`, build a real merge/push governance
enforcement point, document the policy, add the Audit/Change Governance
Agent, add tests, commit.

## 1. Real current repo state (checked first, per task instructions)

```
$ git remote -v
(empty)
$ git branch -a
* master
```

No GitHub remote is configured for `D:\DV\Task\DV_Agent_Harness_L5\v50`.
The entire history is direct commits to a local-only `master` branch --
there is no live PR workflow today. The policy and its enforcement below
are written and active regardless (per the task's own instruction), so
they are already in force the moment a real remote is added.

## 2. gh CLI install

Installed via winget (`winget install --id GitHub.cli -e ...`), it was not
present before this task:

```
$ "/c/Program Files/GitHub CLI/gh.exe" --version
gh version 2.99.0 (2026-09-01)
https://github.com/cli/cli/releases/tag/v2.99.0
```

Installed to `C:\Program Files\GitHub CLI\gh.exe`. winget adds this to the
machine/user `PATH`, but the already-open shell in this session does not
pick that up until a new shell is started (confirmed: `gh --version` from
a bare `PATH` lookup in this session's existing bash still reports "not
found"; invoking the full install path works). This is a normal
Windows/winget PATH-refresh behavior, not an install failure -- a new
terminal will see `gh` on `PATH` directly.

## 3. Real, callable enforcement point

`dv_harness/git_governance.py` -- pure, unit-tested decision logic
(`evaluate_pre_push`, `evaluate_pre_merge_commit`). BLOCKS a direct
push/merge into a protected branch (`main`/`master`) only when BOTH hold:
(a) the destination is protected, (b) the calling process carries an
AI-agent environment marker. It reuses `tools/remote/remote_relay.py`'s
own `AI_AGENT_ENV_MARKERS` constant via direct import (not a duplicated
list) -- the same detection pattern that module's own Layer 2 guard
already established for an analogous problem (an agent invoking a
privileged operation it must not perform itself). Unlike that module,
this gate has **no override variable** -- there is no sanctioned automated
flow under which an agent should ever push/merge `main`/`master` directly.

Wired into the CLI as `dv-harness git-guard --check {pre-push,pre-merge-commit}`
(`dv_harness/cli.py`), and into two real git hook templates:
- `tools/git-hooks/pre-push` -- pipes real githooks(5) stdin refspecs
  through to the decision logic.
- `tools/git-hooks/pre-merge-commit` -- resolves the current branch
  (git itself doesn't pass this) and passes it through.

Install: `git config core.hooksPath tools/git-hooks` (see
`tools/git-hooks/README.md` for the full install/layering/testing
writeup, including the deliberate fail-open behavior if Python is
missing, and why server-side branch protection remains the PRIMARY gate
once a remote exists).

Every decision that actually touched a protected branch (blocked-for-an-
agent, or allowed-for-a-human) is logged as a `GIT_GUARD_DECISION` event
into `.dv-harness/events.jsonl` -- the SAME real audit substrate every
other "who changed what, when" view already reads (`dv-harness audit`,
the dashboard Audit panel) -- no second/parallel audit file was invented.

## 4. Documentation

- `CLAUDE.md`: new "## gh CLI + PR-Only Governance Policy (2026-09-03)"
  section, added right before the existing "## Remote Control Mode"
  section. Checked first for existing git-safety language to avoid
  duplication -- found none specific to a main/master merge policy in
  CLAUDE.md itself (`CORE/git-push-gate` and `CORE/git-workflow` skills
  cover general push/commit hygiene and force-push prohibition, but
  neither previously stated a PR-only/no-direct-merge-main rule) -- the
  new section cross-references both rather than restating their content.
- `.claude/skills/CORE/git-push-gate/SKILL.md`: added a short "## PR-Only
  Merge Policy (main/master)" section cross-referencing CLAUDE.md and the
  real enforcement module, per the Methodology Consolidation Rule (a
  validated policy belongs in the relevant skill file, not only in
  conversation-level prose).

## 5. Audit / Change Governance Agent

`.claude/agents/audit-change-governance-agent.md` -- read-only
(`disallowedTools: Edit, Write`, matching `memory-agent.md`'s convention
for a non-writing specialist). Documents its real responsibilities:
answer "what changed, by whom/which agent, when, with what evidence, is
it reversible" using ONLY real, already-existing evidence sources this
harness has:
1. `.dv-harness/events.jsonl` via `dv-harness audit` (existing).
2. `git log`/`git show`/`git diff` (existing, real).
3. `GIT_GUARD_DECISION` events (new, this task).
4. `gh pr list`/`gh pr view` (real once a remote exists -- honestly
   documented as currently empty).
5. Memory-tier `rtl_sha`/`tb_sha`/`knowledge_commit_sha` provenance
   (existing, from the earlier Obsidian+Git memory work).
6. LSF job state files (existing).

It explicitly does NOT write code, run jobs, commit, branch, push, merge,
or approve/cosign anything -- it is a read-only evidence-aggregation
specialist over infrastructure that already exists, per the user's own
framing ("這個 agent 不負責寫 code / 跑 job，讓 harness 知道做了什麼、可
以追、可逆").

`.claude/agents/ROSTER.md` updated (21 -> 22 real agents, entry inserted
alphabetically). `dv_harness_tests/test_stats_snapshot.py`'s
`test_agent_count_matches_real_glob` hardcoded count was already stale at
20 (preflight-resource-guard-agent had bumped the real count to 21 without
updating this test in the prior workstream) -- corrected to 22 and the
changelog comment extended to record both additions.

## 6. Tests (real, mocked env -- never a real push/merge to a real remote)

- `dv_harness_tests/test_git_governance.py` (30 tests) -- pure logic:
  marker detection, ref parsing, protected-branch matching, and the real
  decision matrix (agent+protected=BLOCKED, human+protected=ALLOWED,
  agent+unprotected=ALLOWED) for both `evaluate_pre_push` and
  `evaluate_pre_merge_commit`. Also asserts `AI_AGENT_ENV_MARKERS` is the
  SAME object as `remote_relay.AI_AGENT_ENV_MARKERS` (reuse, not
  duplication) and that this gate has no override variable.
- `dv_harness_tests/test_cli_git_guard.py` (9 tests) -- real subprocess
  `python -m dv_harness.cli git-guard ...` against a fresh temp project,
  simulated AI-agent env via the real subprocess `env=` kwarg, covering:
  allow/block for both hooks, exit codes, the `GIT_GUARD_DECISION` audit
  event actually landing in `.dv-harness/events.jsonl` and being visible
  through the existing `dv-harness audit` command, and no audit event for
  a non-protected-branch push.

```
$ python -m pytest dv_harness_tests/test_git_governance.py dv_harness_tests/test_cli_git_guard.py -q
39 passed in 30.17s
```

Also re-verified adjacent/shared surfaces were not broken:
```
$ python -m pytest dv_harness_tests/test_stats_snapshot.py dv_harness_tests/test_agent_roster_doc.py \
    dv_harness_tests/test_remote_relay.py dv_harness_tests/test_cli_preflight.py \
    dv_harness_tests/test_preflight_lsf_wiring.py -q
95 passed (1 pre-existing hardcoded-count test fixed, see section 5)

$ python tools/verification_flow/agent_skill_binding_gate.py --root .
{"status": "PASS"}
```

The full `dv_harness_tests/` suite was not run to completion for this
report: this working tree currently has substantial *uncommitted,
in-progress* concurrent work from other parallel workstreams in the same
session (pueue, `just`/run_profile, ntfy/apprise escalation -- see section
7), so a full-suite run right now would also be exercising code that is
not part of this task and may not itself be finished/committed yet. The
targeted runs above cover every file this task actually touched or added.

## 7. Concurrency note (important for the committer)

While working, this session observed live, uncommitted edits to several
shared files (`dv_harness/cli.py`, `dv_harness/config.py`,
`dv_harness/lsf_client.py`, `dv_harness/regression_reporter.py`,
`dv_harness/signoff_export.py`) from what is evidently a concurrent
sibling workstream implementing `just`/pueue/ntfy-apprise (other items
from the same original user spec). None of that work belongs to this
task. To avoid committing someone else's in-progress, unverified changes:
- `dv_harness/cli.py` was staged via a hand-built patch containing ONLY
  this task's two additions (the `git-guard` subparser and its dispatch
  branch), applied with `git apply --cached` against the index -- the
  working-tree file (which still has the sibling edits) was never
  touched, and the sibling's own hunks remain uncommitted for whoever owns
  that workstream to commit separately.
- Every other file staged for this commit was verified via `git diff
  --stat` to contain ONLY this task's own changes before `git add`.
- `config.py`/`lsf_client.py`/`regression_reporter.py`/`signoff_export.py`
  and other untracked sibling files/directories were left completely
  alone (not staged, not modified).

## Real known gaps / follow-ups

- No real GitHub remote exists yet, so `gh pr create`/branch-protection
  configuration and the Audit Agent's `gh pr list` source have nothing
  real to operate against today -- both are ready the moment one is
  added (see CLAUDE.md section 3 above).
- The local hook is a defense-in-depth convenience, not a security
  boundary (bypassable via `--no-verify` or simply not installing it) --
  server-side branch protection remains the authoritative gate; this is
  documented explicitly in `tools/git-hooks/README.md` rather than left
  implicit.
