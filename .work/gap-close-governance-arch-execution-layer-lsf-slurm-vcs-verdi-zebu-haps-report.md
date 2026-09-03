# Gap-Close Pass: Execution Layer -- LSF/Slurm -> VCS/Verdi/ZeBu/HAPS

Date: 2026-09-04
Scope: one layer of the layered-architecture re-verification (Execution Layer only).
Mode: LOCAL_ANALYSIS (pure local read/inspection; no server contact, no VCS run).

## Result

**NO_ACTION_NEEDED** for the in-scope parts (LSF, VCS, Verdi).
**NEEDS_SEPARATE_EFFORT** for Slurm, ZeBu, HAPS.

**No file was modified. No commit was made.**

---

## Independent re-confirmation of the audit's evidence

I re-derived every cited fact myself rather than trusting the audit text. Line
numbers below are current-tree numbers; several differ from the audit's because
`dv_harness/lsf_client.py` and `dv_harness/cli.py` are concurrently modified by
other active workflows in this repo. The substance holds in every case.

### LSF (bsub) -- REAL_AND_CONNECTED (confirmed)

- Real `subprocess.run` wrappers around real LSF binaries in
  `D:\DV\Task\DV_Agent_Harness_L5\v50\dv_harness\lsf_client.py`:
  `bsub_submit()` (argv `["bsub", "-q", queue, "-n", ...]`, lsf_client.py:296-328),
  `_run_bjobs()` (`bjobs -json -o ...`, lsf_client.py:331-347),
  `_run_bjobs_with_fallback()` (lsf_client.py:350-402), `discover_live_jobs()`
  (`bjobs -a`, lsf_client.py:427+), `bkill_job()`.
- The gate is structural, not advisory: `bsub_submit_with_preflight()`
  (lsf_client.py:234-294) runs `preflight.run_preflight()` FIRST and raises
  `PreflightBlockedError` so `bsub_submit()` is never reached on a BLOCKED result.
- CLI wiring confirmed verbatim: `cli.py:225` documents `lsf-submit`'s `command`
  argument as "The command line bsub should run (e.g. the vcs/simv invocation)."
  and `cli.py:1115` calls `lsf_client.bsub_submit_with_preflight(...)`. That is the
  literal LSF -> VCS edge the diagram draws.
- The generated environment's Makefile-native path is equally real:
  `dv_harness/uvm_generator/templates/sim_scripts/lsf_run.sh:7` -- "Every VCS
  invocation in the Makefile goes through this" -- with real `bsub -K` / `bsub` /
  `bsub -Is` modes and a real recorded incident (job 93426, TERM_OWNER,
  lsf_run.sh:28-30). `register_external_job()` bridges that path into `JobState`.

### VCS -- REAL_AND_CONNECTED (confirmed)

- Real two-stage `vlogan` / `vcs -f vcs.opt` flow in
  `dv_harness/uvm_generator/templates/sim_scripts/Makefile`, invoked through
  `lsf_run.sh`.
- The preflight gate is built specifically around a real VCS license check:
  `preflight.py:104` `license_features: ["VCSRuntime"]`, checked by
  `check_license()` (preflight.py:240-275) via a real
  `lmutil lmstat -a -c <server>` command.

### Verdi -- PARTIALLY_REAL, but the residual is NOT a code/wiring gap

The audit's Verdi cause has two parts. I checked both.

**(a) "No session evidence of a live Verdi invocation."** True, and it is an
environment/execution fact, not missing wiring. `make verdi`
(Makefile:2912-2929) is a real, evidence-grounded LSF-connected Verdi
invocation -- it hard-exits when `$(PAT_FSDB)` does not exist, and it carries
this site's real verbatim tool error as its justification for the LSF option:

    Error! Verdi only can be lauch by LSF.
    Please use LSF options by append -lsfon or -lsfint

so `LSF_VERDI`/`LSF_VERDI_QUEUE` route Verdi through `LSF_TOOL_OPT`, and
`-dbdir $(SIMV).daidir` reads the KDB that the `-kdb` flags in both build stages
(Makefile:1510-1578) actually produce. Exercising it requires a completed
pattern run with `WAVE=1` to produce an FSDB. `MEM-809B74A548` records that the
live `usb31_dev_uvm` build has no completed pattern yet (TCA hang), so there is
no FSDB for Verdi to open. Nothing in code can close that; the blocker is
upstream in the simulation, not in the LSF->Verdi edge.

**(b) "preflight's license_features defaults to VCSRuntime only, no Verdi
feature checked."** Real observation, but it is already a configurable knob that
is fully threaded end-to-end -- there is no disconnection to wire:

- `dv_harness/config.py:140` carries `"license_features": ["VCSRuntime"]` in the
  real project config schema,
- `dv_harness/cli.py:1090` and `:1111` build the config via
  `_preflight.config_from_dict(h.cfg.get("preflight"))`,
- `dv_harness/engine.py:2767` does the same on the engine path,
- `dv_harness/degradation.py:262` likewise.

A project that wants a Verdi feature gated adds it to `config.json`; no code
change is required for that to take effect.

**Why I deliberately did NOT hardcode a Verdi feature name.** The only real
captured `lmstat` evidence this repo holds
(`dv_harness_tests/test_preflight.py:53-64`, gathered 2026-09-03 against the
real server `2900@host-a`) lists exactly two features: `VCSRuntime` and
`VCSCompiler`. No Verdi feature name appears in it. Adding a guessed name
(`Verdi`, `Verdi3`, `novas`, ...) to the default would be inventing evidence,
and `test_preflight.py:112-116` proves the concrete consequence: naming
`license_features=["Verdi"]` against this site's real lmstat output makes
`check_license()` return FAIL "not found", which would BLOCK every submission on
this project. That change would make the harness less correct, not more, and it
violates the Evidence Truth Rule. The honest close for this sub-item is a
site-specific `config.json` entry once someone captures the real Verdi feature
name from a full `lmstat -a` -- a configuration action for the project owner,
not a code fix, and per this pass's rule 3 I did not attempt it.

Additionally, Verdi is already gated at the environment level today:
`preflight.py:100-101`'s default `required_env_vars` is
`["VCS_HOME", "UVM_HOME", "VERDI_HOME"]`, so a submission with `VERDI_HOME`
unset is already BLOCKED by the same real gate.

### Slurm -- ASPIRATIONAL, NEEDS_SEPARATE_EFFORT

Re-grepped every `sbatch|squeue|sinfo|scancel|slurm|Slurm|SLURM` hit under
`dv_harness/`. There is no Slurm submission path: no `sbatch` subprocess call, no
Slurm client module, no `squeue`/`sinfo` call. `preflight.check_queue_health()`
is hardcoded to LSF (`preflight.py:296` -- `cmd = f"bqueues {cfg.queue}"`).

One nuance the audit did not name, worth recording: `sbatch` is not purely prose.
`dv_harness/pueue_client.py:198` has `FARM_SUBMIT_COMMANDS = ("bsub", "sbatch")`,
a real functional guard that REFUSES a pueue task whose command would run a raw
`sbatch` around the preflight gate. So the only working `sbatch` code path in the
harness is one that *rejects* it. Every other hit (cli.py:322/330/352/1185,
escalation_notify.py:256, lsf_client.py:242, preflight.py:4-5, pueue_client.py
docstrings) is prose pairing "bsub/sbatch" or "LSF/Slurm" as a conceptual label.

**Why I did not build `slurm_client.py` in this pass.** The pass's own priority
is "wire REAL existing pieces together over building new parallel mechanisms."
A Slurm client would be a new parallel mechanism, and -- decisively -- there is
no Slurm infrastructure anywhere in this environment to validate it against. The
only real scheduler evidence this project holds is LSF on host-a/host-c. Writing an
unexercisable `sbatch` wrapper would ADD aspirational code and make the
diagram-vs-reality honesty problem worse, not better, while producing tests that
could only ever assert against mocks of a scheduler nobody here has. That is a
genuine new capability requiring a real Slurm site to verify, not a wiring fix.

### ZeBu -- ASPIRATIONAL, NEEDS_SEPARATE_EFFORT

Only reference in the entire tree is `dv_harness/memory_vault.py:363`, the static
list entry `"05_Tools/ZeBu"` -- an empty Obsidian vault folder name. Zero
functional code, zero submission path, zero compile/run flow. Explicitly named
out of scope by this pass's own rule 3 (hardware-emulation bring-up is a large
new capability, and validating it would require actual ZeBu platform access that
this environment does not have).

### HAPS -- ASPIRATIONAL, NEEDS_SEPARATE_EFFORT

Three real occurrences, all documentation/comment notes about a hypothetical
hierarchy-index difference for a hypothetical future HAPS build
(`sim_scripts/waves.tcl:96-97,111`, `sim_scripts/apb_timing_report.sh:34`,
`sim_scripts/Makefile:1171`), plus the same empty vault-folder placeholder
`"05_Tools/HAPS"` at `memory_vault.py:363`. `+define+HAPS` is never set anywhere.
This is a conditional guard anticipating a future target, not a working path.
Same out-of-scope reasoning as ZeBu.

---

## Verification

No production code was changed, so this is a re-confirmation run rather than a
regression proof of a fix.

    python -m pytest dv_harness_tests/test_preflight.py \
                     dv_harness_tests/test_lsf_client.py \
                     dv_harness_tests/test_preflight_lsf_wiring.py \
                     dv_harness_tests/test_execution_preflight_wiring.py -q
    -> 141 passed in 39.08s

## Repo-hygiene note

`dv_harness/lsf_client.py`, `dv_harness/cli.py`, `dv_harness/engine.py` and
others are currently modified in the working tree by concurrent workflows (a
14-AI-mechanism audit/close pass and a live remote USB build). I touched none of
them; no `git add`, no staging, no commit was performed by this pass.

## Recommendation to the owner (not actioned here)

The one genuinely fixable item this layer surfaces is a **documentation** one,
not a code one: the diagram's "LSF / Slurm" and "ZeBu / HAPS" boxes name
capabilities that do not exist in code. Renaming that box to "LSF" and marking
ZeBu/HAPS as planned would make the diagram match reality at zero risk. That is
the user's own diagram, so this pass did not edit it unilaterally.
