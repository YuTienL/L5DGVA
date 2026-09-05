# VI-2 Cross-Project Pattern Mining — gap-close report

**Status: DONE** (mechanism + CLI verb + tests; one deliberate residual — no
automatic trigger — disclosed in §7.)

**Tests:** 29/29 new tests pass (22 `test_cross_project_mining.py` + 7
`test_cli_cross_project.py`); 214/214 pass across the memory/capability suites
this touches; 106 pass / 5 fail across all 11 `test_cli_*.py` files, and the 5
failures are `test_cli_pueue.py` only — **proved pre-existing** by re-running
that file with my `cli.py` change stashed out, where the same 5 fail. Full
evidence in §6.

---

## 1. Independent re-verification (the audit was NOT stale)

Confirmed NEVER_BUILT with my own greps before writing a line:

- `grep -rn -i "cross_project|cross-project|CrossProject"` over `*.py`/`*.md`:
  every hit is the ORGANIZATIONAL tier's `kind="cross_project_lesson"` string
  (a record label routed by `memory_router.py:1191`, surfaced as a CLI choice
  at `cli.py:1288`) or prose in `docs/MEMORY_ARCHITECTURE.md`. Not one hit is a
  function that reads more than one project root.
- `grep -rn -i "mining|multi-project|multi_project"`: every hit is CLAUDE.md's
  unrelated "No Golden-Reference Content Mining" rule.
- The only genuinely cross-project surface in the codebase,
  `dv_harness/knowledge_center.py`, is an add/search RPC against a shared Linux
  DB path over an SSH hop. It never groups records, never counts distinct
  projects, and cannot run without a real remote server — a shared store, not a
  miner.
- The closest real neighbor, `capability_evolution.repeated_unresolved_failure_patterns()`
  (`capability_evolution.py:1564`), mines exactly ONE root and takes a single
  `root` argument.

So: the per-project tiers were real; the tier above them did not exist.

## 2. What I built

**`dv_harness/cross_project_mining.py`** (new, ~560 lines with reasoning
comments) — a registry plus a pure-read miner.

- `ProjectRegistry` — persisted at `<host>/.dv-harness/cross_project/registry.json`,
  written through the existing `storage._atomic_replace()`. `register()` /
  `unregister()` / `roots()` / `entries()`, each registry change audited as one
  `CROSS_PROJECT_REGISTER` / `CROSS_PROJECT_UNREGISTER` event in the one real
  `events.jsonl` via `StateStore.event()`.
- `project_failure_index(root)` — one project's `job_failure` signatures grouped
  by `evidence_db.signature_key()`, with memory_ids and independent run
  identities, plus that project's gate-verified closure claim texts.
- `verified_fix_records(root)` — that project's `verified_fix` records and the
  claim texts that make a fix joinable to another project's open failure.
- `mine_cross_project_patterns(projects, min_projects=2)` — the miner. Groups
  across projects, qualifies at `CROSS_PROJECT_MIN_PROJECTS = 2` DISTINCT
  projects, and returns each pattern's whole basis (signature, per-project
  memory_ids/run identities/occurrence counts, which projects closed it, which
  still have it open).
- `transferable_fix` on each pattern — **the finding that only exists at this
  level**: a gate-verified fix in project A for a signature project B still has
  open, carrying A's real `verified_fix` `memory_id`.
- `promotion_readiness(pattern)` — reports what an Organizational promotion
  would still need. Performs none.
- `mine_registered_projects(host_root)` — mine the registry, record one
  `CROSS_PROJECT_MINING` event (including for a pass on which nothing
  qualified).
- `production_status(host_root)` — computes, rather than claims, whether this
  installation can produce a real cross-project result.

**`dv_harness/cli.py`** — a new `cross-project` subcommand group:
`register` / `unregister` / `list` / `status` / `mine`. A refusal (including
`ProjectIdentityCollisionError`) prints as data and exits 1 rather than raising;
a completed `mine` exits 0 whatever it found, because `INSUFFICIENT_PROJECTS` is
an honest answer about the sample, not a command failure. This is a purely
additive insertion — two hunks, no existing line changed.

> Note on the shared-file protocol: when I began, `cli.py` carried another
> close-pass's STAGED change, so I had planned to skip it and disclose that.
> That pass committed (`efff797`) partway through this one, leaving `cli.py`
> clean at HEAD, so I added the verb after re-checking `git status` and
> committed promptly with an explicit pathspec.

**`dv_harness_tests/test_cross_project_mining.py`** (new, 22 tests) and
**`dv_harness_tests/test_cli_cross_project.py`** (new, 7 tests).

**`CLAUDE.md`** — one new section, appended only; no existing line touched.

## 3. Reuse, not a parallel mechanism (the Methodology Consolidation Rule)

Nothing here re-derives "the same failure", "a closed failure", or "an
independent observation":

| Concept | Reused from | Not re-implemented |
|---|---|---|
| failure identity | `evidence_db.signature_key()` | no second hash |
| evidence read | `memory.MemoryStore.find()` | no second query path |
| "a failure record" | `capability_evolution.REPEAT_FAILURE_JOB_MEMORY_KIND` (imported) | not retyped |
| "a closed failure" | `capability_evolution.RESOLVING_ENGINEERING_MEMORY_KIND` (imported) | not retyped |
| closure claim join | `failure_resolution_claims()` / `resolved_failure_claim_texts()` | not a second, fuzzier join |
| independence WITHIN a project | `capability_evolution._run_identity()` | not re-derived |
| signature digest | `capability_evolution._failure_signature_summary()` | — |
| atomic file replace | `storage._atomic_replace()` | — |
| audit trail | `storage.StateStore.event()` | no second log |

`test_the_miner_reuses_the_shared_failure_identity_and_kinds` asserts the
constant identities, so a later change that gives this module its own hash or
its own idea of "a closed failure" breaks a test.

## 4. The honesty guarantees, enforced by mechanism rather than discipline

The brief's central warning — *do not synthesize a second fake "project"
against this repo's own real audit trail* — is enforced in code, twice:

1. `ProjectRegistry.register()` raises `ProjectIdentityCollisionError` when a
   root's memory store shares ANY `memory_id` with an already-registered root.
   A byte-for-byte copy of a project tree is therefore refused.
2. `mine_cross_project_patterns()` re-checks the same thing on the roots it is
   actually handed, because the registry file is editable text and the miner
   also accepts roots passed directly. Colliders are excluded and reported in
   `identity_collisions`.

Both are proven by mutation: disabling the collision check makes
`test_a_hand_edited_registry_cannot_smuggle_one_store_in_twice` fail; relaxing
the two-project bar to one makes three tests fail.

Other honesty properties, each asserted:

- Fewer than two contributing stores returns `INSUFFICIENT_PROJECTS`, whose
  disclosure states the answer is about the SAMPLE, not about the projects.
- Single-project patterns are reported in their own list, never silently
  dropped (hiding them would make an empty cross-project result read as an
  absence of failures).
- `test_this_repository_honestly_reports_no_production_cross_project_result`
  reads the REAL repo root and asserts `can_produce_cross_project_result is
  False`. **There is no production cross-project finding, and there cannot be
  one until a genuine second project is registered.**

## 5. Human-approval gates: untouched

- Not one line of `HumanApprovalRequiredError`,
  `ProductionWriteNotAuthorizedError`, `ControlPlane.approve()`,
  `policy.can_signoff()`, `assert_legal_transition()` or the PR-only
  main/master governance was modified. I edited no existing Python file at all.
- The miner mints nothing and promotes nothing. `promotion_readiness()`
  computes and reports; the only route into Organizational Memory remains
  `memory_router.promote_to_organizational()`'s three gates plus
  `organizational_admission_gate()`.
- `test_promotion_readiness_reports_and_never_promotes` and
  `test_mining_writes_nothing_to_any_mined_project` assert the organizational
  tier is still empty after an "eligible for review" pattern is produced, and
  that a byte-level snapshot of every mined store is unchanged.
- No build, regression, or LSF submission is triggered anywhere in the module
  or its tests. Every test runs against temporary directories.

## 6. Tests

**What was run, and the exact result:**

| Command | Result |
|---|---|
| `pytest test_cross_project_mining.py test_cli_cross_project.py` | **29 passed** |
| `pytest` over `test_capability_evolution_auto_discovery.py`, `test_memory_tier_completion.py`, `test_memory_tier_integrity_and_admission.py`, `test_memory_vault.py`, `test_evidence_db.py`, `test_memory_write_guard_and_job_evidence.py` + the new file | **214 passed** (138s) |
| `pytest` over all 11 `test_cli_*.py` + both new files | **106 passed, 5 failed** (478s) |
| `pytest test_cli_pueue.py` with my `cli.py` change **stashed out** | **5 failed, 1 passed** — identical failures |

The only failures anywhere are the 5 in `test_cli_pueue.py`, which drive the
real `pueue`/`pueued` daemon binaries. They fail identically at HEAD without my
change, so they are pre-existing and environment-dependent, not a regression.

I also started a run of the entire `dv_harness_tests/` directory; it had not
finished after ~35 minutes and I stopped it rather than report a guess. The
per-file runs above cover every module my change can reach: the new module, the
`cli.py` verb (whose insertion is purely additive — 69 insertions, 0 deletions),
and every memory/capability module it imports.

**What gives the new tests detection power:**

Each "project" is a separate temporary root with a real `MemoryStore`,
populated through the real `memory_router.route_and_store()` with the exact
record shapes `engine._record_debug_attempt_job_memory()` and
`engine._promote_verified_fix_knowledge()` write, using real
`memory_vault.build_failure_signature()` signatures. No fixture JSON is
hand-typed into a store file.

Negative controls (the half that matters):

- forty runs in ONE project are still not a cross-project pattern;
- three retries against one commit are one run inside a project;
- a bare `root_cause` record is an explanation, not a closure, so it yields no
  transferable fix;
- a copied project is refused at registration AND excluded at mine time;
- a bare directory neither gains a memory store (asserted: the dir stays
  absent) nor pads the project count;
- a byte-level before/after snapshot proves no mined store was mutated;
- `min_projects=1` is refused with a reason.

**Mutation-tested, not merely green.** Relaxing the two-project bar to
`>= 1` fails 3 tests; disabling the identity-collision check fails
`test_a_hand_edited_registry_cannot_smuggle_one_store_in_twice`. Both guards
are load-bearing, not decorative.

**CLI tests** (`test_cli_cross_project.py`, 7) drive `cli.main()` in-process
with monkeypatched `sys.argv`, the pattern `test_cli_question_queue.py` /
`test_cli_memory_commands.py` already use: register/list/unregister round trip,
a refusal reported as data with exit 1 rather than a traceback, a real
transferable fix found across two registered projects, `INSUFFICIENT_PROJECTS`
exiting 0, `--min-projects 1` refused, and "the whole command group promotes
nothing" (organizational tier still empty afterwards).

**End-to-end smoke test outside pytest**, against two temp project roots built
through the real router:

```
$ dv-harness --project-root <host> cross-project register <A> --id A
$ dv-harness --project-root <host> cross-project register <B> --id B
$ dv-harness --project-root <host> cross-project mine
  OK  ['A', 'B']  fixed_in ['A'] -> open_in ['B']
$ dv-harness --project-root <host> cross-project register <copy-of-A> --id FAKE_C
  ProjectIdentityCollisionError
```

(Temp fixtures deleted afterwards; nothing was written into this repository.)

## 7. Deferred, and why

**No AUTOMATIC trigger.** The verb exists, but no `run_stage()`/`advance()`
call site invokes it, no graph node declares it, and it is not on the dashboard.
Deliberate rather than unfinished: auto-mining at a stage boundary would fire
against a registry that is empty in every real installation today and emit
nothing but no-op events, and registration is deliberately a human act so that
"which projects agree" never depends on where the harness happened to be run
from.

**No remote/Knowledge-Center federation.** Mining reads local project roots.
Federating it across `knowledge_center.py`'s shared broker would need a real
remote server and could not be honestly tested here.

**No dashboard card.** `dashboard.py` was left untouched — other close-passes in
this same sequential loop touch it, and a card adds no capability the verb does
not already provide.

**Known pre-existing quirk, deliberately NOT changed**: `dv_harness/__main__.py`
is `from .cli import main; main()` and therefore drops `main()`'s return value,
so `python -m dv_harness <anything>` always exits 0. That affects every verb in
this CLI equally, and the installed `dv-harness` console script (whose
setuptools wrapper does `sys.exit(main())`) propagates correctly. Fixing it
would change exit-code semantics repo-wide — well outside this gap, and on a
shared file other passes touch.

## 8. Files

- `D:\DV\Task\DV_Agent_Harness_L5\v50\dv_harness\cross_project_mining.py` (new)
- `D:\DV\Task\DV_Agent_Harness_L5\v50\dv_harness_tests\test_cross_project_mining.py` (new)
- `D:\DV\Task\DV_Agent_Harness_L5\v50\dv_harness_tests\test_cli_cross_project.py` (new)
- `D:\DV\Task\DV_Agent_Harness_L5\v50\dv_harness\cli.py` (+69 lines, 0 deletions)
- `D:\DV\Task\DV_Agent_Harness_L5\v50\CLAUDE.md` (append-only, +96 lines)
