# Gap 3 — Harness-to-Remote-Agent-Path Deployment: DONE

**Scope**: `self_check_list.md` items #37-39, harness-codebase half only. The
Knowledge Center write-back half (`dv_harness/knowledge_center.py`) was already
real and wired and was not touched.

**Mode**: LOCAL_ANALYSIS throughout. No network call was made to
`/home/svcacct/AI/Agent` or any other remote host at any point. Every test and
every demonstration below ran against a local synthetic target directory or a
locally-constructed transcript.

## Audit verdict re-confirmed independently before building

The supplied audit's **NEVER_BUILT** verdict is correct. Re-verified with real
commands rather than accepted from the brief:

- `grep -rniE "harness_deploy|deploy_harness|push_harness|sync_harness|svcacct/AI/Agent"`
  over `--include=*.py --include=*.json --include=*.md --include=justfile`:
  every hit is prose (`REMOTE_LOGIN_GUIDE.md`, `USAGE_MULTI_USER_SAFETY.md`,
  `START_HERE.md`, `KNOWLEDGE_CENTER_GUIDE.md`), a test fixture string in
  `test_remote_exec.py`/`test_remote_relay.py`, or a MEMORY record *narrating* a
  past hand-performed sync (`MEM-34FD025AD6`, `MEM-36006EC300`, `MEM-72BE64EEB3`,
  `MEM-7F419E5BA8`, `MEM-B239D45EFF`, `MEM-DBAE7300BF`, `MEM-EA3FCC5DA5`,
  `MEM-F869C96ECB`, `MEM-FE50DF8367` — nine records saying "synced to
  /home/svcacct/AI/Agent" with no tool named). Zero implementation hits.
- Exhaustive `add_parser(...)` listing of `dv_harness/cli.py` (all ~130
  subcommands): no `deploy`, `harness-sync`, `push-remote` or equivalent. Only
  `memory sync` (Obsidian vault, different subsystem) and `resync-notes`.
- `tools/` and `dv_harness/` contain no `*deploy*`/`*sync*` script targeting a
  remote path.

One correction to the audit's framing, found while reading: `DEBUG_WORKFLOW_GUIDE.md:126`
says "No new mechanism is needed" — but that sentence is about running
simulation in a DE's *own* `DVWORKDIR`, not about deploying the harness. It is
not evidence that this gap was considered and declined.

## What was built

Three new files, plus a wire into the existing CLI and a CLAUDE.md section.

| file | role |
|---|---|
| `dv_harness/harness_deploy.manifest.json` | **Policy as data** — what "the harness" IS (`include`/`exclude`/`never_sync`), same shape as `context_budget.policy.json`. |
| `dv_harness/harness_deploy.py` | The mechanism (~640 lines). |
| `dv_harness_tests/test_harness_deploy.py` | 49 tests. |
| `dv_harness/cli.py` | `dv-harness harness-deploy manifest\|plan\|apply` front door. |
| `CLAUDE.md` | Consolidation section, per the Methodology Consolidation Rule. |

### Extended, not duplicated

Every piece the audit identified as a reusable building block is reused
unchanged:

- **Diff engine**: `tools/remote/source_identity.py`'s `three_way_diff()` /
  `aggregate_source_id()` — the same primitive `server_sync_identity_gate.py`
  uses to *verify* PC-vs-server identity, used here to *compute a push delta*.
  Not one line of hash math was re-derived.
- **Remote manifest ingestion**: `tools/verification_flow/_remote_transcript.py`'s
  `REMOTE_HOST=`/`EXIT_CODE=`/`STATUS=` marker check over a real captured
  `remote_exec.py "md5sum ..."` stdout — the identical convention
  `server_sync_identity_gate.py` established.
- **Transport**: `remote_hop.py`'s documented tar → `--put` → `tar xzf` pattern,
  narrowed to the diff set instead of the whole tree. Only `remote_exec.py` is
  ever named; `remote_relay.py` never is (asserted by a test).
- **Audit trail**: `StateStore.event()` → one `HARNESS_DEPLOY_SYNC` entry in the
  same `.dv-harness/events.jsonl` that `dv-harness audit` and the dashboard
  already read. No second audit file.
- **One implementation, two front doors**: `cli.py` and
  `python -m dv_harness.harness_deploy` both call one `execute_verb()`. A test
  drives both and asserts identical output, so they cannot drift into the
  parallel-mechanism defect this project forbids.

### Three safety properties, each enforced in code and tested

1. **Never blind-overwrite.** Push set is `local_only ∪ different` only.
   `remote_only` is surfaced as a required human decision (exit code 3) and
   never deleted. A test applies a plan and asserts a server-only file survives.
2. **Never ship a credential.** `never_sync` **raises** rather than silently
   skipping. This is not hypothetical: `replay.ps1` — the real, gitignored
   (`.gitignore:11`), untracked local credential script CLAUDE.md's Remote Linux
   Execution amendment describes — sits in this checkout's root, and the
   destination is a shared multi-user path.
3. **Never reach the network by accident.** `plan` makes zero network calls *by
   construction* (remote side is a local directory or a local transcript file).
   The relay path builds the tarball and **prints** the command sequence unless
   `--execute` is passed; the `execute=True` code path is tested through an
   injected `run_fn`, so no test can reach a relay.

Additional refusals, all tested: an absent `--target-root` is a refusal, never
an empty remote (a typo must not read as "the target has nothing" and push the
whole harness somewhere wrong); a first-ever deployment must be **declared**
with `--assume-remote-empty`, never inferred; a marker-less or nonzero-exit
transcript is a refusal, never a short manifest that would read as "the server
is missing everything".

### Three real defects found and fixed during the build

**1. CRLF-vs-LF would have made the tool useless against the real server.**
This is the significant one, and it was not in the brief. This checkout's
`core.autocrlf` is `true`, so the Windows working copy holds CRLF while git's
blobs — and therefore a `git clone`-populated `/home/svcacct/AI/Agent`, which is
exactly how `USAGE_MULTI_USER_SAFETY.md:37-39` and `REMOTE_LOGIN_GUIDE.md:34-38`
describe that tree being created — hold LF. Verified on this checkout:

```
dv_harness/engine.py   CRLF md5 = 020fb26f0e7db0523dfe14ddc99e8eec
dv_harness/engine.py     LF md5 = a14df5e9b461d8b3080e1f20e21885b1
```

A naive md5 diff would therefore report every text file as `different` on every
plan, forever — re-pushing the whole harness each run and never once reaching
`in_sync`. **A diff that is always maximal is not a diff.**
`classify_line_ending_only_differences()` compares the remote md5 (all a
transcript carries) against *both* line-ending renderings of the local bytes, so
it needs no remote content and works on the transcript path that matters against
the real server. Measured against the real 993-file tree with an LF-normalized
synthetic target:

```
default (tolerant):      in_sync=True   push=0     line_ending_only=204   exit 0
--strict-line-endings:   in_sync=False  push=204   line_ending_only=0     exit 1
```

204 files of phantom drift, eliminated. Tests hold the boundary: a genuine
content change that *also* crosses a line-ending boundary stays in `push` (the
most expensive possible failure would be silently refusing to deploy a real
change), and a binary file — detected by a NUL byte, the same cheap heuristic
git itself uses — is never normalized.

**2. Non-deterministic tarball**: `tarfile.open(path, "w:gz")` stamps the current
time and the local file's own name into the gzip header, so two packs of
identical content differed. Fixed with an explicit `gzip.GzipFile(mtime=0,
filename="")` wrapper. Caught by a test, not by inspection.

**3. Audit-trail bloat**: a first sync pushes 993 files; inlining every path
appended ~100KB to a single `events.jsonl` line that `dv-harness audit` and the
dashboard read back. Path lists are now capped at `EVENT_PATH_LIST_CAP = 50`
with the true total, a truncation flag and both SOURCE_IDs always recorded in
full.

## Real evidence (no network)

```
$ dv-harness harness-deploy apply --target-root <synthetic>
status=APPLIED copied=993                                       exit 0

$ dv-harness harness-deploy plan --target-root <synthetic>
in_sync=True push=0
local_sid =e4c19186a43e5123085cbe1ebc37240823c0ce399fbb1d4475a2d393b7bb1e4a
remote_sid=e4c19186a43e5123085cbe1ebc37240823c0ce399fbb1d4475a2d393b7bb1e4a   exit 0
```

Then, after drifting one file on the synthetic target and adding a server-only
file to it:

```
$ dv-harness harness-deploy plan --target-root <synthetic>
in_sync=False push=1 push_list=dv_harness/gates.py
remote_only=dv_harness/server_hotfix.py needs_decision=True                   exit 3
```

And the remote transport path, driven from a locally-built transcript:

```
$ dv-harness harness-deploy apply --remote-md5sum-transcript <local file>
status=PREPARED executed=False files=1 tgz_bytes=28785
remote_only_untouched=dv_harness/server_hotfix.py                             exit 0

python tools/remote/remote_exec.py "mkdir -p /home/svcacct/AI/Agent/.harness_deploy"
python tools/remote/remote_exec.py --put <local>.tgz /home/svcacct/AI/Agent/.harness_deploy/<name>.tgz
python tools/remote/remote_exec.py --cwd /home/svcacct/AI/Agent "tar xzf .../<name>.tgz -C /home/svcacct/AI/Agent && rm -f .../<name>.tgz"

why_not_executed: execute=False (the default). Run the printed commands from a
session that has completed CLAUDE.md's SSH/Remote Transport Connection Intake,
or re-invoke with --execute from such a session.
```

Note the delta is **1 file / 28KB**, not the whole 993-file tree — the
incremental behavior is real, not asserted.

## Test summary

`python -m pytest dv_harness_tests/test_harness_deploy.py -q` → **49 passed**.

The full 5258-test suite was run serially in two halves (the first background
run was killed at 65% by the harness, so the remaining 80 files were run as a
second process — noted because cross-file ordering effects *between* the halves
are therefore not reproduced):

| segment | result |
|---|---|
| files up to `test_qualification.py` (~3418 tests) | 8 failed, 6 errors |
| remaining 80 files (`test_pueue_preflight_gate.py` → `test_workflow_rca_multi_agent_fusion.py`) | **1935 passed, 0 failed** |

Every one of the 14 is accounted for, and none is attributable to this change:

- **5 F `test_cli_pueue.py` + 6 E `test_pueue_client.py`** — the known
  environmental baseline: `pueued` does not start on this machine. Reproduced
  and attributed in four prior session reports
  (`gap-close-3loop-gap-1-report.md:168`,
  `gap-close-capability-evolution-acceptance-tests-report.md:298`,
  `gap-close-asset-table-9-level-conflict-authority-order-mismatc-report.md:35`,
  `gap-close-governance-arch-preflight-...-report.md:121`). Nothing here touches
  pueue.
- **1 F `test_capability_evolution_controlled_experiment.py::test_a_hand_written_benchmark_result_is_refused`**
  — a concurrent session's mid-edit state (`capability_evolution.py` and its
  schema were `M` in the shared tree at that moment). **Re-run after they
  committed: passes.**
- **2 F `test_dashboard_interactive.py` coverage tests** — cross-file order
  dependence, pre-existing. **Verified: both pass in isolation, and the whole
  file passes 54/54 standalone.** They also run alphabetically *before*
  `test_harness_deploy.py`, so this change cannot be their cause, and the only
  `CLAUDE.md` reference in that file is a comment on line 1177.

## Commit: what actually happened (read this before assuming a scoped commit)

**This work is committed, but NOT as its own scoped commit, and not by me.**
While the full suite was running, a *concurrent session* in this same working
tree ran a broad `git add` and swept all five of my files into **its** commit,
`e0a3002 "capability_evolution: real controlled-experiment execution +
harness-deploy mechanism"`, alongside its own unrelated capability_evolution
work. That commit contains, at their final content:

```
dv_harness/harness_deploy.py             | 860 +
dv_harness/harness_deploy.manifest.json  |  83 +
dv_harness_tests/test_harness_deploy.py  | 684 +
dv_harness/cli.py                        |  71 +   (mixed: my 2 hunks + theirs)
CLAUDE.md                                | 208 +   (mixed: my 103 lines + theirs)
```

Verified after the fact: `git diff dv_harness/harness_deploy.py
dv_harness/harness_deploy.manifest.json dv_harness_tests/test_harness_deploy.py`
is **empty** against HEAD — the committed content is my final version, not a
mid-edit snapshot — and `git show HEAD:CLAUDE.md | grep -c
"Harness-to-Remote-Agent-Path Deployment"` returns 1. Nothing of mine is left
uncommitted; the remaining working-tree delta in `CLAUDE.md`/`cli.py` is that
other session's `loop_convergence` work (`@@ -1865,0 +1866,108 @@` and
`@@ -1461,0 +1462,9 @@`), which I have not touched.

**I did not rewrite history to re-scope it.** The content is already in a
pushed-branch ancestor; splitting it out would mean rewriting shared history,
which is not sanctioned and is far worse than a mixed commit message. Recorded
here instead so `git log` alone does not mislead a future reader about which
change this report describes.

**Before that happened**, my two shared files were verified to carry only my own
hunks: `git diff -U0 dv_harness/cli.py` → exactly 2 hunks, both pure insertions
(`@@ -1382,0 +1383,51 @@`, `@@ -2812,0 +2864,20 @@`); `git diff -U0 CLAUDE.md`
→ one hunk, `@@ -1544,0 +1545,103 @@`, appended at end of file. Zero deletions
in either. The concurrent session's own in-flight files were deliberately never
staged by me.

**Process lesson worth keeping**: two agents sharing one working tree means a
broad `git add` by either one captures the other's in-progress edits. Scoped
`git add <explicit paths>` is not merely tidier here — it is the only thing that
keeps commits attributable at all.

## Method note: the suite was NOT run under pytest-xdist

An attempt to shorten the 5258-test serial run with `-n 8 --dist loadfile`
produced failures that do not reproduce serially, including
`FileNotFoundError: ...\\.dv-harness\\telemetry\\stages\\STAGE-*.tmp` — this
suite has tests that drive real subprocesses and share the repo-root
`.dv-harness/` state directory, so parallel results are not trustworthy here.
Recorded so a future pass does not repeat the attempt and read the noise as
regressions.

## Disclosed residuals

- This closes the **mechanism**, not an executed deployment. No sync to the live
  `/home/svcacct/AI/Agent` was performed — that is REMOTE_EXECUTION and requires
  a fresh SSH/Remote Transport Connection Intake confirmation this workflow does
  not have.
- Nothing calls `harness-deploy` **automatically**: no post-commit hook, no CI
  step. "Every harness update must sync" is still a human-run verb. This is a
  REACHED capability (a real CLI caller exists), not a WIRED one — the same
  honest distinction `.claude/agents/ROSTER.md` applies to `research-architect`.
  Wiring it to a real trigger is a separate, bounded follow-on.
- The `.claude` → `industrial`/`PACKAGE` sync (Methodology Consolidation Rule,
  `CLAUDE.md:571-572`) is a **different, still-unautomated** concern: those are
  local sibling directories, not the remote Linux path. This tool's manifest
  could be pointed at them via `--target-root`, but no recipe does so today.
