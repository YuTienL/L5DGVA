# Gap close — Preflight Agent (lmstat / disk / env / queue / host)

**Status: DONE**

Scope: the one part of the governance-architecture re-verification covering the
Preflight Agent node and its edges (Execution Layer → Preflight Agent →
LSF/Slurm; Graph/Planner → Preflight Agent).

---

## 1. Re-confirmation of the audit's cited evidence (independently checked)

| Claim | Re-check | Result |
|---|---|---|
| `dv_harness/preflight.py` implements 6 real checks, no stubs | read the file (469 lines) | CONFIRMED |
| The module's own suites pass | `pytest dv_harness_tests/test_preflight.py test_preflight_lsf_wiring.py test_cli_preflight.py -q` | **52 passed** |
| `bsub_submit()` has exactly one non-test call site, inside `bsub_submit_with_preflight()` | `grep -rn "bsub_submit(" dv_harness/ tools/` | CONFIRMED — the only real call is `dv_harness/lsf_client.py:286`, reached only after `run_preflight()` |
| `engine.py` never calls preflight/bsub | grep | CONFIRMED, and consistent with the diagram (Preflight Agent is drawn under the Execution Layer, not under Graph/Planner) — not a gap |

So the node and both real submission edges were, and remain, REAL_AND_CONNECTED.

## 2. The gap that was real, and is now closed

The audit named exactly one concrete, bounded, not-yet-true item:

> `pueue_client.py`'s prevention of a raw un-gated `bsub`/`sbatch` inside a pueue
> task is **documentation/convention only**, not enforced code.

That was accurate. `PueueClient.add()` accepted any command string, so
`pueue add "bsub -q vcs simv"` (or the same thing hidden in the project's own
`python tools/remote/remote_exec.py "..."` step shape) would have launched a real
farm job with `preflight.run_preflight()` never consulted — routing around the
"沒過就 BLOCKED，不派 job" rule every other path enforces. The Execution Layer →
Preflight Agent edge was real for the CLI/justfile paths and merely conventional
for the pueue path.

### What changed

**`dv_harness/pueue_client.py`** — new enforced guard, wired into the existing
code rather than added as a parallel mechanism:

- `find_farm_submit_tokens()` / `_farm_submit_hits()` — detects a `bsub`/`sbatch`
  in real **command position** only: first word of a shell segment, past a leading
  `FOO=bar` assignment, or anywhere past a wrapper (`ssh host bsub …`,
  `python tools/remote/remote_exec.py "bsub …"` — the load-bearing case, since
  that is this project's own documented pueue step shape). `grep bsub sim.log`,
  `./rerun_bsub_failures.sh` and `bsubmit` are correctly **not** matches.
- `gated_submit_markers()` — the accepted spelling is read off the **live code
  object** (`lsf_client.bsub_submit_with_preflight.__name__`) plus the real CLI
  subcommand `lsf-submit`, so renaming the gated entry point moves the marker
  instead of leaving the guard accepting a dead string.
- `assert_farm_submission_is_preflight_gated()` — raises
  `UngatedFarmSubmissionError` unless the marker appears in the **same shell
  segment** as the token, so `dv-harness lsf-submit A && bsub -q vcs B` is refused
  rather than laundered by the adjacent gated step.
- `UngatedFarmSubmissionError` is deliberately **not** a `PueueError` subclass —
  same reasoning `lsf_client` already uses to keep `PreflightBlockedError` distinct
  from `LsfUnavailableError`: a caller must never absorb "the harness refused an
  un-gated submission" as "pueue itself failed".
- `add()` calls the guard **before** building argv, so no `pueue add` is ever
  invoked for a refused command. `enqueue_harness_chain()` pre-validates **every**
  step before the first `add()`, so an offending step leaves the chain entirely
  un-enqueued rather than half-started.
- `allow_ungated_farm_submit=False` is the single named, greppable override,
  mirroring `bsub_submit_with_preflight()`'s own explicit `skip_preflight` opt-out
  rather than inventing a second exemption style. It exists for the guard's known
  false-positive shape (a task that merely mentions the token past a wrapper) and
  is **not** exposed as a CLI flag.

**`dv_harness/cli.py`** — `pueue add` and `pueue chain` report the refusal as its
own `{"error": "UNGATED_FARM_SUBMISSION", "tokens": [...], "use_instead":
"dv-harness lsf-submit"}` payload with **exit 2**, distinct from
`PUEUE_ADD_FAILED`. `chain` gate-checks every step *before* touching the daemon,
so a refusal never degrades into `PUEUED_NOT_AVAILABLE` on a machine without
pueue installed. Help text updated on all three parsers (stale "the real
bsub/sbatch call is one caller-supplied step command" wording corrected).

**`dv_harness_tests/test_pueue_preflight_gate.py`** — new, 35 tests.

### Tests that prove the connection (not each piece in isolation)

The task's requirement was a test proving the two things the diagram connects are
actually connected. `TestAcceptedTaskCommandReallyReachesPreflight` drives one
task string end to end:

1. the guard **accepts** `dv-harness lsf-submit "simv +UVM_TESTNAME=…" --queue vcs
   --run-dir …` and enqueues it byte-for-byte (never rewritten);
2. that subcommand's handler is verified against the real `cli.py` source to be
   the call site of `lsf_client.bsub_submit_with_preflight(`;
3. that entry point, driven for real, calls `preflight.run_preflight()` first and
   `bsub_submit` **not at all** on BLOCKED;
4. a real-subprocess `dv-harness lsf-submit …` on this machine (no `lmutil`/
   `bqueues`/`df` present) genuinely returns `PREFLIGHT_BLOCKED`, exit non-zero —
   the real absence exercising the real gate, per `test_cli_preflight.py`'s
   existing convention.

The mirror-image refusal tests assert the injected `ProcRunner` recorded **zero**
calls, i.e. the refusal happened before pueue was reached, not after a task was
already queued.

## 3. Disclosed residual (NOT closed, deliberately)

The audit's second half — "nothing stops a human from running `make compile`
directly, bypassing `just build`'s preflight prerequisite" — is **not** closed
here. A pueue task string of `make compile` (or `just build`) carries no literal
`bsub`/`sbatch` token; the submission happens inside the generated environment's
own Makefile via `LSF ?= 1`. Blocking `make` at this layer would refuse legitimate
non-LSF local builds, and the fix belongs in the generated Makefile / justfile,
both of which are being modified by other agents right now. Recorded as a separate
hardening item, not silently claimed as done.

## 4. Verification

```
pytest test_pueue_preflight_gate.py test_preflight.py \
       test_preflight_lsf_wiring.py test_cli_preflight.py -q     -> 87 passed
```

**Pre-existing failures, not caused by this change — proven, not assumed.** The
wider run (`test_pueue_client.py` + `test_cli_pueue.py` added) shows
`5 failed, 117 passed, 6 errors`. All 11 are the REAL-pueue-daemon tests:
`ensure_daemon()` returns False / the CLI prints `PUEUED_NOT_AVAILABLE` because
`pueued` will not come up on this machine right now (the binaries *are* installed
at `~/bin/pueue.exe`/`pueued.exe`, so this is not a missing-binary skip).

Verified against a pristine `git worktree` of HEAD rather than inferred:

| Tree | `test_cli_pueue.py` | `test_pueue_client.py` |
|---|---|---|
| pristine HEAD | **6 failed** | 30 passed, **6 errors** |
| this change | **5 failed** | 30 passed, **6 errors** |

Identical errors, and one *fewer* failure here: moving the `NO_STEPS` check ahead
of `ensure_daemon()` fixed `test_chain_with_no_steps_errors`, which previously
died on the dead daemon before reaching its own assertion.

**Commit**: `07d9967` — *preflight: enforce the pueue -> preflight gate in code,
not convention*. `dv_harness/cli.py` was staged as a hand-scoped patch
(`git apply --cached` of only my five hunks) because other agents are editing it
concurrently; their `regression-tier` hunks were verified absent from the commit.

Files touched: `dv_harness/pueue_client.py`, `dv_harness/cli.py` (hand-scoped
patch — this file is concurrently modified by other agents),
`dv_harness_tests/test_pueue_preflight_gate.py` (new).
