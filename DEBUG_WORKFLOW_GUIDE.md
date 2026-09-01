> See START_HERE.md for the canonical entry point. This page covers the
> end-to-end loop for debugging a `UVM_ERROR` in a DE's own generated
> VIP-based verification environment, driven from Claude Code on the PC.
> See `REMOTE_LOGIN_GUIDE.md` for the underlying relay/`remote_exec.py`
> mechanics this page builds on, and `USAGE_MULTI_USER_SAFETY.md` for why
> every path below is the DE's own, never the shared
> `/home/svcacct/AI/Agent` tree.

# AI Agent Harness L5 — Debug Workflow Guide

## Enforcement status (verified by code audit, 2026-09-02)

Every step below was audited against the actual wired pipeline (not just
read as prose) and 6 of 8 confirmed gaps between "documented" and
"code-enforced" have since been closed — see
`.work/persist_debug_workflow_gap_closure_memory.py` for the full
before/after evidence. Two gaps remain honestly open, noted inline below
(steps 4 and 5) rather than silently glossed over.

Prerequisite: the DE has completed onboarding
(`REMOTE_LOGIN_GUIDE.md`'s "Onboarding a new PC user" section) — their own
`--project-root`, their own relay started with **their own `VCUSER`**
(never the shared `svcacct` service account — see REMOTE_LOGIN_GUIDE.md's
"The permission model" section: the relay executes every command as a
real Unix login, and `svcacct` has no standing access to a DE's own
home-directory tree), `DVWORKDIR` pointing at their own generated
environment's Linux-server deployment path (e.g.
`/home/tmpacct/devuser/UVM/USB`). Debugging *someone else's* environment
requires that other account's real permission grant or credentials — see
REMOTE_LOGIN_GUIDE.md for the options; there is no way around real Unix
file permissions.

## The loop, stage by stage

1. **Don't open waveform first.** Per `CLAUDE.md`'s Simulation
   Observability Default, the first regression pass runs with FSDB OFF.
   Start by reading `sim.log` for the real `UVM_ERROR` — most of what's
   needed to form a hypothesis is already there.
2. **Targeted waveform rerun only for the failing case(s).** Per
   `CLAUDE.md`'s First-Failure Waveform Rerun rule: rerun only the
   testcase(s) that actually produced a `UVM_ERROR` or an abnormal
   termination (fatal/crash/timeout) — never re-enable waveform for the
   whole batch — with the minimum sufficient scope/depth, and terminate at
   (optionally slightly past) the first relevant failure point.
3. **Waveform Dump User Gate — DE confirms scope before it happens.**
   Before any waveform-enabled sim, the harness must ask the DE to confirm
   dump scope and depth. This is a required stop, not a formality — never
   let it silently default to full-chip/full-depth.
4. **Evidence gathering (`FAILURE_RECOVERY` / `RE_AUDIT` stages).** The
   harness collects: `sim.log`'s `UVM_ERROR` context, the FSDB waveform
   from step 2 (code-enforced: `focused_wave_debug_window_gate` is wired
   into `STAGE_GATES["FAILURE_RECOVERY"]`), checker/assertion output, and
   — when relevant — current RTL source and register/programming state
   (`deep_rca_evidence_gate` independently recomputes a real file's sha256
   when a source's `evidence_path` is supplied, catching a stale/fabricated
   citation). **Still open**: an automatic Knowledge Center
   (`/home/svcacct/AI/DB`) lookup before concluding a fresh root cause is
   NOT yet wired in — `KnowledgeCenterClient.search()` is currently only
   reachable via the manual `dv-harness knowledge search` command; check it
   yourself before trusting the harness already did.
5. **Every root-cause claim must cite current evidence**, not a prior
   session's memory or a similar-looking past bug — see `CLAUDE.md`'s
   Evidence Truth Rule. Code-enforced for `deep_rca_evidence_gate` sources
   with an `evidence_path` (real hash recompute, see step 4). **Still
   open**: `root_cause_evidence_gate`'s `supporting_evidence`/
   `counter_evidence` fields remain free-text citations with no equivalent
   freshness check yet.
6. **DE reviews and rules — Human Override is authoritative.** Especially
   when the evidence is ambiguous or the question is "is this really a bug
   or is this the spec's intended behavior" — that call belongs to the DE,
   not the harness. Code-enforced for the case that matters most: a
   DUT_BUG classification or a high-risk fix at `RE_AUDIT` now hard-stops
   at `WAIT_USER` until a real `dv-harness approve` call is recorded in
   `.dv-harness/control.json` — `fix_risk_approval_gate` cross-checks that
   real record, not just the agent's own self-declared boolean. A
   TB_BUG/low-risk fix is unaffected (no approval required, to avoid
   friction on routine testbench fixes).
7. **Apply the fix.** An RTL fix is the DE's own to make (the harness
   proposes root cause and direction, it does not rewrite DUT core logic
   on its own authority). Code-enforced: `.claude/settings.json` denies
   both `Edit` and `Write` on this project's `DUT/**`/`VIP/**` paths,
   `block-destructive.ps1` blocks a Bash-level write targeting them, and
   `rtl_write_scope_guard_gate` (`STAGE_GATES["IMPLEMENT"]`) checks the
   agent's own attested touched-files list against the project's
   configured `rtl_protection.protected_paths`. A testbench/VIP/checker-side
   fix is generated by the harness from primary sources (VIP manual/RTL/spec
   — never mined from a different finished reference environment, per
   CLAUDE.md's No-Golden-Reference-Content-Mining rule), and still needs DE
   approval.
8. **Redeploy, then verify narrow before verifying broad**: single failing
   case first, full regression second (see "Redeploying the regenerated
   environment" below). Code-enforced as a real precondition:
   `regression_selection_completeness_gate` (`STAGE_GATES["REGRESSION_SELECT"]`
   — the actual gate immediately before a regression submits) now requires
   single-test reverify evidence when following a fix cycle, and
   `fix_regression_non_regression_gate` cross-checks a claimed pre/post-fix
   result against a real `JobState` record when a `job_id` is supplied.
9. **Persist the lesson.** Once `RE_AUDIT`'s `fix_effectiveness_gate` AND
   `fix_regression_non_regression_gate` both PASS, the harness now
   automatically builds a `kind="verified_fix"` record and pushes it to
   the shared Knowledge Center (`engine.py`'s
   `_promote_verified_fix_knowledge()`) — no manual persistence script
   needed for this common case.

## Running simulation in the DE's own working path

The DE's environment lives at their own `DVWORKDIR`
(e.g. `/home/tmpacct/devuser/UVM/USB`), never the shared
`/home/svcacct/AI/Agent` tree. No new mechanism is needed — the same
`remote_exec.py` bridge from `REMOTE_LOGIN_GUIDE.md` is used directly:

```
# DVWORKDIR already set once in the DE's terminal session
python tools/remote/remote_exec.py "make WAVE=1 TEST=usb_error_test"

# or point explicitly deeper into the environment's own layout
python tools/remote/remote_exec.py --cwd /home/tmpacct/devuser/UVM/USB/sim "make WAVE=1 TEST=usb_error_test"
```

Two practical limits to respect:

- **A single `remote_exec.py` call has a hard 1800s ceiling**
  (`Session.run()`'s own module docstring: "NEVER run a long build/
  regression in the foreground through this"). A single targeted
  First-Failure Waveform Rerun (one case, minimal waveform, cut at the
  first failure point) normally fits. A full regression-length run must
  be launched with `nohup ... &` and polled with separate, short
  `remote_exec.py` calls — never issued as one long foreground call.
- **LSF-queued work** (`bsub`) goes through `dv-harness lsf submit` /
  `dv-harness lsf-watch-start` — the only path that's actually been
  verified to keep the `regression.list` safety net and job-state
  reconciliation working automatically; don't hand-roll polling for
  LSF-queued jobs.

## Redeploying the regenerated environment

After the harness regenerates/edits testbench/VIP files locally (under the
DE's own `--project-root`'s generated output), push the changes to the
DE's own `DVWORKDIR` — same transfer mechanism used everywhere else in
this harness, never the shared code tree:

```
# few files: put them individually
python tools/remote/remote_exec.py --put <local-file> "<DVWORKDIR>/<relative-path>"

# many files: tar locally, put the tarball, extract remotely
tar czf update.tgz -C <project-root>/generated <changed-subdir>
python tools/remote/remote_exec.py --put update.tgz "<DVWORKDIR>/update.tgz"
python tools/remote/remote_exec.py --cwd <DVWORKDIR> "tar xzf update.tgz"
```

**Git Bash/MSYS warning**: if any of these Unix-style path arguments
(`--put`'s REMOTE, `--cwd`, `DVWORKDIR`) get silently rewritten into a
Windows path by Git Bash before Python sees them, `remote_exec.py` now
fails loudly with an `MSYS_NO_PATHCONV` instruction instead of silently
corrupting the transfer (real incident, 2026-09-02 — see
`USAGE_MULTI_USER_SAFETY.md`'s changelog). If you hit that error, prefix
the command with `MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'`.

Then, **verify narrow before verifying broad**:

1. Re-run only the originally-failing testcase. Confirm the `UVM_ERROR` is
   actually gone AND that the evidence (sim.log, and waveform if still
   enabled) supports that conclusion — not just a clean exit code.
2. Only then re-run the full regression, to confirm the fix didn't
   introduce a new regression elsewhere.
3. Persist the verified fix to the Knowledge Center (step 9 above).
