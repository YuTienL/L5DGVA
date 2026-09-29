# Worktree Detail — Gate 1

**Execution mode: LOCAL_ANALYSIS.** Read-only `git worktree list --porcelain`, `git status`, `git log`, `git reflog`, `git branch --merged` against the local `.git` metadata only. No file in any worktree was created, modified, or deleted.

## Correction to a prior framing

The earlier `10_WORKTREE_AUTHORITY.md` correctly retracted the fabricated `.gitignore`-comment claim and correctly identified 8 real worktrees at `D:/wt/`, but described them only as "external" without checking whose `.git` they belong to. **They are not external to `v50` — they share `v50`'s own `.git`.** `git -C v50 worktree list` lists all 9 (the `v50` checkout itself plus the 8 at `D:/wt/`) as worktrees of the same repository. This does not change the Phase-1 disposition (still no in-repo `.worktrees/`/`.claude/worktrees/` consolidation decision made), but it does change what "purpose/owner" evidence is available: since it's the same repository, branch/commit/authorship history is fully inspectable, and that evidence is used below.

## Per-worktree detail

| Worktree | Branch | HEAD | Ahead of `master` | Behind `master` | Merged into `master`? | Dirty files | Author (all commits) |
|---|---|---|---|---|---|---|---|
| `D:/wt/b1` | `impl/b1` | `42863cf` | 0 | 2 | **Yes** | 0 (clean) | Peter Lin |
| `D:/wt/b2` | `impl/b2` | `5e21072` | 0 | 4 | **Yes** | 1 (`dv_harness/dashboard.py` modified) | Peter Lin |
| `D:/wt/b4` | `impl/b4` | `5e21072` | 0 | 4 | **Yes** | 1 (`dv_harness/dashboard.py` modified — identical file to `b2`) | Peter Lin |
| `D:/wt/b5` | `impl/b5` | `5e21072` | 0 | 4 | **Yes** | 4 (`engine.py`, `harness_status.py`, `question_queue.py`, `test_harness_status.py`) | Peter Lin |
| `D:/wt/b6` | `impl/b6` | `5e21072` | 0 | 4 | **Yes** | 2 (`cli.py`, `models.py`) | Peter Lin |
| `D:/wt/b7a` | `impl/b7a` | `7b2a65a` | 1 | 4 | **No** | 1 untracked (`dv_harness/rtl_filelist_parser.py`) | Peter Lin |
| `D:/wt/b7b` | `impl/b7b` | `c7c7fa0` | 1 | 4 | **No** | 2 (`vip_capability_extraction.py`, its test) | Peter Lin |
| `D:/wt/b8` | `impl/b8` | `c9cdd06` | 1 | 4 | **No** | 1 (`amba_fabric_generator.py`) | Peter Lin |

`master` HEAD at time of this review: `9abb10f` ("Add GUI-02 Protocol Selector dashboard card; fill in human-control-plane and gav-mode SKILL.md").

## Branch state, in plain terms

- **`b1`, `b2`, `b4`, `b5`, `b6` — fully merged, stale.** Each branch's tip commit is already an ancestor of `master` (`git rev-list --count master..impl/bN` = 0 for all five). Their work has landed; the worktree checkouts are now behind `master` by 2–4 commits and exist only as leftover parallel-dispatch checkouts. `b2` and `b4` carry the exact same one-line-uncommitted `dashboard.py` diff — consistent with two worktrees created from the same dispatch batch that were never both driven to completion, or one being an accidental duplicate of the other.
- **`b7a`, `b7b`, `b8` — real, unmerged, active work.** Each has exactly 1 commit not yet in `master` (`Close DUT-10/DUT-04`, `VIP-01/VIP-02 multi-vendor VIP-home scanning`, `Wire verification_architecture IR + system_virtual_sequencer composition_mode`) plus its own uncommitted working-tree changes. These are genuinely open, in-progress implementation branches — not stale.

## Creation mechanism

`git reflog show impl/bN` for every one of the 8 branches shows only `branch: Created from master` at `5e21072` as its earliest reflog entry, immediately followed (where applicable) by that branch's own commit(s). **No script, workflow file, or committed automation anywhere in the `v50` tree references `D:/wt/` or issues `git worktree add`** (a full-tree grep for `D:/wt`, `D:\wt`, and `worktree add` found no matching automation — the one incidental `worktree add` hit in `.work/gap-close-self-check-*.md` refers to an unrelated one-off baseline worktree at `/tmp/gap4_baseline`, not this pattern). The creation mechanism is therefore **not discoverable from repository content** — it was an external/session-time action (consistent with a parallel multi-agent implementation-batch dispatch pattern, e.g. this harness's own `Workflow`-tool-style `isolation: "worktree"` fan-out), not a documented repo convention. This absence-of-automation is itself evidence worth recording: the `D:/wt/bN` convention is real and repeatedly used (8 instances, consistent naming) but institutionally undocumented.

## Naming-scheme gap

Branches exist for `b1, b2, b4, b5, b6, b7a, b7b, b8` — **`b3` does not exist** as a branch, in the reflog, or anywhere else searched. No evidence explains the gap (an intentional skip in an external numbering scheme vs. a deleted/never-created batch are equally unsupported by anything in this repository). Disclosed, not resolved.

## Owner / purpose evidence

All commits on all 8 branches are authored by the same single git identity (`Peter Lin`), consistent with the project's own confirmed single-user-machine status (see `CLAUDE.md`'s Remote Linux Execution amendment). No per-branch ticket/task-ID metadata beyond the commit subject lines themselves was found; the commit subjects are self-describing enough to infer purpose (e.g. `b7a` = DUT-10/DUT-04 gap closure, `b7b` = VIP multi-vendor scanning, `b8` = verification-architecture IR wiring) and are quoted above rather than paraphrased.

## References from `v50` to these worktrees

None found. No file in the `v50` working tree (root, `.claude/`, `.dv-harness/`, `docs/`, `tools/`) names `D:/wt/` or any `impl/bN` branch. The relationship is entirely git-internal (shared `.git`, branch refs), not documented anywhere a human or Claude session would read it without running `git worktree list` directly.

## Disposition (unchanged from Phase 1)

No worktree was deleted, modified, or moved. This review does not select an authoritative worktree-staging location — see `AUTHORITY = HUMAN_DECISION` in `10_WORKTREE_AUTHORITY.md`. It does add one new fact relevant to that future human decision: 5 of the 8 external worktrees are stale/merged and could be pruned (`git worktree remove`) with no loss of unmerged work, while 3 (`b7a`, `b7b`, `b8`) hold real unmerged commits plus uncommitted changes and must not be pruned without first committing/merging or explicitly discarding that work.
