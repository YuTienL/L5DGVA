# DV Agent Harness L5 -- fixed recipes for the project's real
# PUSH -> BUILD -> VERIFY -> WAVE=1 RUN -> FSDBREPORT pipeline.
#
# Source of truth for every command below (never invented):
#   - .claude/skills/CORE/remote-executor/SKILL.md   the canonical
#     PUSH/BUILD/VERIFY/WAVE=1 RUN/FSDBREPORT sequence and its documented
#     no-git-remote PUSH variant (tar czf -> --put -> tar xzf).
#   - dv_harness/uvm_generator/templates/sim_scripts/Makefile   the real
#     `make compile`/`make sim`/`make regress`/`make check`/`make
#     list_patterns` targets and variables (FLOW, PATTERN, SEED, WAVE, COV,
#     SUITE, LSF*).
#   - dv_harness/preflight.py + `dv-harness preflight`/`lsf-submit` CLI
#     (dv_harness/cli.py)   the real lmstat + scheduler preflight gate from
#     the Preflight/Resource Guard workstream (.work/governance-preflight-
#     report.md). Every recipe that can trigger a remote job submission
#     (LSF_COMPILE/LSF_SIM default to LSF=1 in the Makefile) depends on
#     `preflight` first, so a BLOCKED verdict stops the recipe chain before
#     `make` ever runs -- matching the user's own spec ("bsub / sbatch 前先
#     做 license、queue、host、disk、workdir、EDA env 檢查。沒過就 BLOCKED，
#     不派 job").
#   - tools/remote/remote_exec.py + tools/remote/remote_hop.py   the real
#     transport this harness uses from the Windows PC side (persistent
#     relay; VCHOST/VCHOP already set as OS env vars this session -- see
#     replay.ps1). fsdbreport's flag grammar is dv_harness/fsdb_report.py's
#     own CONFIRMED grammar; this justfile calls the real `fsdbreport`
#     binary directly over the relay rather than assuming dv_harness itself
#     is deployed on the Linux server (unconfirmed -- see
#     .work/governance-just-report.md).
#
# This exists to reduce ad hoc command construction ("Claude 不需要自己拼長
# command，降低誤操作") -- every remote command below is one fixed recipe,
# not something composed free-hand per invocation.
#
# Usage: run `just` (or `just --list`) from this directory. See
# .work/governance-just-report.md for the full design writeup and the real
# `just --list`/`just --dry-run` output this was verified against.

# just's own manual documents exactly this pattern for enabling POSIX (sh)
# recipe bodies on Windows -- every command below is written in the same
# sh/POSIX quoting style already used throughout this project's own scripts
# (lsf_regress.sh, remote_exec.py's own docstring examples), and Git for
# Windows's sh.exe is confirmed present on this machine (installed with the
# git binary already required by this project).
set windows-shell := ["D:/Program Files/Git/bin/sh.exe", "-cu"]

# REAL, CONFIRMED GOTCHA (see tools/remote/remote_exec.py's own 2026-09-02
# comment block): invoking remote_exec.py through Git Bash/MSYS's sh.exe
# auto-rewrites a bare /home/... argument (e.g. --cwd, --put's REMOTE, a
# remote path baked into the quoted command string) into a mangled Windows
# path BEFORE Python ever sees it, unless these two are set. Exported once
# here rather than repeated on every recipe line.
export MSYS_NO_PATHCONV := "1"
export MSYS2_ARG_CONV_EXCL := "*"

# --- Transport / infrastructure identity ------------------------------------
# Already-live OS env vars this session (see replay.ps1, CLAUDE.md's Remote
# Linux Execution section) -- read here only as documented real defaults,
# never as a place a secret is written. VCPW (the password) never appears
# in this file, matching CLAUDE.md's "must never be printed, echoed, quoted,
# or written into any evidence block, log, gate payload, or memory record".
vchost := env_var_or_default("VCHOST", "vchost-b")
vchop := env_var_or_default("VCHOP", "host-c")

python := env_var_or_default("PYTHON", "python")
remote_exec := justfile_directory() + "/tools/remote/remote_exec.py"
dv_harness_cli := "-m dv_harness.cli --project-root \"" + justfile_directory() + "\""

# Remote sim-tree working directory `make`/`vcs` run inside. Real value
# confirmed this session (tools/remote/remote_exec.py's own DVWORKDIR
# docstring example; replay.ps1's real DVWORKDIR). Override per checkout
# with `just build sim_dir=/other/path ...` or the DVWORKDIR env var.
sim_dir := env_var_or_default("DVWORKDIR", "/home/tmpacct/devuser/UVM/USB")

# --- Preflight gate defaults -------------------------------------------------
# Real values confirmed live against the actual remote server 2026-09-03
# (.work/governance-preflight-report.md: bqueues vcs -> Open:Active; lmutil
# lmstat -a -c 2900@host-a -> UP). dv_harness/config.py's shipped
# DEFAULT_CONFIG leaves these empty on purpose (a generic library default
# must never guess another project's infrastructure) -- this justfile is a
# project-root artifact for THIS project's real infrastructure, so pinning
# them here as overridable defaults is the correct layer for that.
queue := env_var_or_default("DV_QUEUE", "vcs")
license_server := env_var_or_default("DV_LICENSE_SERVER", "2900@host-a")
preflight_workdir := env_var_or_default("DV_PREFLIGHT_WORKDIR", "/home/svcacct/DV/UVM/USB/usb_uvm/sim")

# --- Makefile paths/variables ------------------------------------------------
# VIP_HOME/DUT_ROOT_PATH/UVM_ROOT_PATH: left empty by default and simply
# forwarded, never guessed. Passing an empty value still triggers the
# Makefile's OWN `$(error ... is not set)` guards (GNU make's `ifdef` is
# false for an empty value, same as unset), so an unconfigured path fails
# loudly with the Makefile's real message instead of silently building
# against nothing -- confirmed against the real Makefile
# (dv_harness/uvm_generator/templates/sim_scripts/Makefile lines 54-64).
vip_home := env_var_or_default("VIP_HOME", "")
dut_root_path := env_var_or_default("DUT_ROOT_PATH", "")
uvm_root_path := env_var_or_default("UVM_ROOT_PATH", "")
make_paths := "VIP_HOME=" + vip_home + " DUT_ROOT_PATH=" + dut_root_path + " UVM_ROOT_PATH=" + uvm_root_path

# Real Makefile defaults (Makefile lines 2309 FLOW, 208-217 PATTERN, 2936
# SUITE, 213 SEED) -- kept identical so `just build`/`just verify` with no
# overrides behaves exactly like a bare `make compile`/`make sim` would.
flow := env_var_or_default("FLOW", "fourstep")
pattern := env_var_or_default("PATTERN", "smoke")
suite := env_var_or_default("SUITE", "sanity")
seed := env_var_or_default("SEED", "1")

build_timeout := env_var_or_default("DV_BUILD_TIMEOUT", "3600")
run_timeout := env_var_or_default("DV_RUN_TIMEOUT", "1800")

# List every recipe -- `just` with no argument does the same.
default:
    @just --list --unsorted

# =============================================================================
# Transport / gating
# =============================================================================

# Real persistent-relay readiness check (CLAUDE.md: "Check readiness first
# with `python tools/remote/remote_exec.py --status`").
relay-status:
    {{python}} "{{remote_exec}}" --status

# Real lmstat + scheduler preflight gate (dv_harness/preflight.py, via
# `dv-harness preflight --remote`): EDA license (lmutil lmstat), LSF queue
# Open:Active (bqueues), host reachability, disk space, workdir, required
# EDA env vars. Routed through the persistent relay
# (RemoteRelayCommandRunner) since this runs on the Windows PC side -- see
# dv_harness/cli.py's `preflight` subcommand and the workstream report at
# .work/governance-preflight-report.md. Exits 1 on BLOCKED
# (`raise SystemExit(0 if result.overall == "PASS" else 1)`), which is what
# stops every gated recipe below before its `make`/bsub-triggering command.
preflight queue=queue workdir=preflight_workdir license_server=license_server:
    {{python}} {{dv_harness_cli}} preflight --remote --queue {{queue}} --workdir {{workdir}} --license-server {{license_server}}

# =============================================================================
# 1. PUSH
# =============================================================================
# .claude/skills/CORE/remote-executor/SKILL.md's documented no-git-remote
# PUSH variant, verbatim: tar czf locally, --put the archive through the
# relay, tar xzf it open remotely. This project has no git remote between
# the PC and the Linux workdir (see that SKILL.md section), so this tar
# variant -- not a `git push`/`git pull` -- is the real mechanism.
push local_dir remote_dir archive="dv_push.tgz":
    tar czf "{{justfile_directory()}}/.work/{{archive}}" -C "{{local_dir}}" .
    {{python}} "{{remote_exec}}" --put "{{justfile_directory()}}/.work/{{archive}}" "{{remote_dir}}/{{archive}}"
    {{python}} "{{remote_exec}}" --cwd "{{remote_dir}}" "tar xzf {{archive}} && rm -f {{archive}} && find . -type f | wc -l"
    rm -f "{{justfile_directory()}}/.work/{{archive}}"

# Single-file push (a small edit) -- direct --put, no tar round trip. Same
# `remote_exec.py --put <local> <remote>` this project already uses (see
# tools/remote/remote_exec.py's own module docstring example).
push-file local_file remote_file:
    {{python}} "{{remote_exec}}" --put "{{local_file}}" "{{remote_file}}"

# Pull one remote file back (a report, a log, an FSDB) -- the `--get` half
# of the same real mechanism.
pull remote_file local_file:
    {{python}} "{{remote_exec}}" --get "{{remote_file}}" "{{local_file}}"

# =============================================================================
# 2. BUILD
# =============================================================================
# `make compile` (Makefile line 2625: compile: elab) under this project's
# default LSF=1, so LSF_COMPILE (Makefile line 566: `LSF_COMPILE ?= $(LSF)`)
# submits the vcs elaboration through the site's own -lsfon bsub wrapper --
# a real job-submission step, hence the `preflight` dependency.
build queue=queue workdir=preflight_workdir license_server=license_server: (preflight queue workdir license_server)
    {{python}} "{{remote_exec}}" --cwd "{{sim_dir}}" --timeout {{build_timeout}} "make compile FLOW={{flow}} {{make_paths}} LSF_QUEUE={{queue}}"

# =============================================================================
# 3. VERIFY
# =============================================================================
# remote-executor SKILL.md's VERIFY step: the targeted testcase/scenario,
# Coverage OFF, WAVE OFF -- the real first pass per CLAUDE.md's Simulation
# Observability Default ("Normal simulation/regression defaults to FSDB
# OFF"). `make sim PATTERN=<n> WAVE=0` (Makefile: sim: $(SIMV); run: dirs).
# Also a real job-submission step under LSF_SIM (Makefile line: `LSF_SIM ?=
# $(LSF)`), hence the same `preflight` dependency.
verify pattern=pattern seed=seed queue=queue workdir=preflight_workdir license_server=license_server: (preflight queue workdir license_server)
    {{python}} "{{remote_exec}}" --cwd "{{sim_dir}}" --timeout {{run_timeout}} "make sim PATTERN={{pattern}} SEED={{seed}} WAVE=0 {{make_paths}} LSF_QUEUE={{queue}}"

# Batch equivalent of VERIFY -- `make regress SUITE=<name> LSF=1`, first
# pass with FSDB off, per CLAUDE.md's "Regression-batch pipeline shape"
# note: "The first pass runs the full batch with FSDB OFF". A regression is
# long-running, so per remote-executor SKILL.md's own Transport note ("長跑
# 的 BUILD/VERIFY/regression ... 用 bsub/nohup ... & 送出，再用短的
# remote_exec.py 'bjobs <id>' 輪詢") this submits under `nohup ... &` and
# returns immediately rather than blocking remote_exec.py for the whole
# suite -- poll with `just regress-log`.
regress suite=suite queue=queue workdir=preflight_workdir license_server=license_server: (preflight queue workdir license_server)
    {{python}} "{{remote_exec}}" --cwd "{{sim_dir}}" "nohup make regress LSF=1 SUITE={{suite}} {{make_paths}} LSF_QUEUE={{queue}} > regress_{{suite}}.out 2>&1 & echo submitted pid=$!"

# Tail the background regression's own log (Makefile's own documented
# pattern: `nohup make regress LSF=1 SUITE=sanity > regress.out 2>&1 &`).
regress-log suite=suite lines="80":
    {{python}} "{{remote_exec}}" --cwd "{{sim_dir}}" "tail -n {{lines}} regress_{{suite}}.out 2>/dev/null || echo 'no regress_{{suite}}.out yet'"

# Static checks only -- include order, VIP class/enum availability, Makefile
# expansion order (Makefile `check:` target, line 2042). Seconds, never
# submits a job, so no preflight dependency (matches the Makefile's own
# help text: "seconds not minutes -- run it before a long build").
check:
    {{python}} "{{remote_exec}}" --cwd "{{sim_dir}}" --timeout 300 "make check {{make_paths}}"

# What patterns exist to pass as PATTERN=/SUITE= above (Makefile
# `list_patterns:` target, line 3196) -- read-only, no job submitted.
list-patterns:
    {{python}} "{{remote_exec}}" --cwd "{{sim_dir}}" "make list_patterns {{make_paths}}"

# --- Bind connectivity: the standing 3-gate recipe ---------------------------
# CLAUDE.md's "Bind-Location Rules (2026-09-03)" makes the 3 machine gates
# (Gate 1 elaboration / Gate 2 static zero-time connectivity / Gate 3
# transaction activity) a REQUIRED checkpoint, and
# dv_harness/connectivity.py's own run_gate3_against_live_simv() docstring
# calls for them as "a standing 'just connectivity-check' recipe re-run on
# every RTL update". These two recipes ARE that -- backed by the real
# dv_harness/connectivity_check.py runner, which drives
# connectivity.run_machine_gates() (all 3 gates, never a subset) and records
# the RTL content fingerprint the resulting verdicts were produced against.
#
# LOCAL, not remote: this reads the local RTL tree and the local
# .dv-harness/ state, submits no LSF job and needs no license, so unlike
# build/verify/run there is deliberately no `preflight` dependency here.
#
# Inputs come from .dv-harness/connectivity_check.json (rtl_sources,
# filelists, top_module, optional signal_trace_path / monitor transaction
# counts / pattern_completed). A project without that file is reported
# NOT_CONFIGURED rather than silently passing.
connectivity-check:
    {{python}} -m dv_harness.connectivity_check --project-root "{{justfile_directory()}}"

# The standing TRIGGER, for CI / a pre-push hook / any "did anything change"
# poll: runs no gate, only compares the current RTL fingerprint against the
# last recorded `just connectivity-check` run. Exit 2 means the RTL moved
# but the gates were not re-run, so the recorded Gate 1/2/3 statuses
# describe different RTL and must not be cited.
connectivity-check-status:
    {{python}} -m dv_harness.connectivity_check --project-root "{{justfile_directory()}}" --check-only

# =============================================================================
# 3b. TIERED REGRESSION CADENCE (2026-09-04, Section 3 item 3c)
# =============================================================================
# Regression used to be flat here: one submission mechanism, one escalation
# threshold, no cadence. These three recipes are the real invocation points
# for the SMOKE/NIGHTLY/WEEKLY tiers defined in dv_harness/regression_tiers.py
# -- each resolves the tier's own test list from the harness-COMPUTED
# change-impact selection (dv_harness/change_impact.py, recomputed here
# against the tier's own base revision) and declares the active tier, which
# is what makes the lsf-watch reconciliation loop apply THAT tier's
# UVM_FATAL escalation threshold instead of the flat one.
#
# HONEST DISCLOSURE: these recipes are the TRIGGER POINT, not the scheduler.
# Nothing in this repo installs a cron entry or a Windows scheduled task --
# doing so is a machine-level act outside version control, and claiming a
# schedule exists when none is installed would be exactly the fabricated
# evidence this project's Evidence Truth Rule forbids. Install one of:
#
#   # Linux crontab -e
#   */30 * * * *  cd <project> && just regression-smoke
#   0 22 * * 1-5  cd <project> && just regression-nightly
#   0 2  * * 6    cd <project> && just regression-weekly
#
#   # Windows Task Scheduler (PowerShell, run once per tier)
#   schtasks /Create /TN "DV nightly regression" /SC DAILY /ST 22:00 ^
#            /TR "cmd /c cd /d <project> && just regression-nightly"
#
# `regression-tier plan` (read-only, declares nothing) is available via
# `dv-harness regression-tier plan <TIER>` for inspecting a tier's test list
# without starting it.
#
# base_sha defaults are per-tier ON PURPOSE: a SMOKE run answers "did the
# change I just made break the sanity set", so it diffs against the previous
# commit; NIGHTLY diffs against the last day of history, WEEKLY against the
# last week. Override on the command line (e.g. `just regression-nightly
# origin/main`) when a project's real baseline is a branch point rather than
# a commit count.
regression-smoke base_sha="HEAD~1":
    {{python}} -m dv_harness.cli --project-root "{{justfile_directory()}}" regression-tier start SMOKE --base-sha "{{base_sha}}"

regression-nightly base_sha="HEAD~10":
    {{python}} -m dv_harness.cli --project-root "{{justfile_directory()}}" regression-tier start NIGHTLY --base-sha "{{base_sha}}"

regression-weekly base_sha="HEAD~50":
    {{python}} -m dv_harness.cli --project-root "{{justfile_directory()}}" regression-tier start WEEKLY --base-sha "{{base_sha}}"

# Read-only: which tier (if any) is currently declared, and therefore which
# UVM_FATAL escalation threshold the watcher is applying right now.
regression-tier-status:
    {{python}} -m dv_harness.cli --project-root "{{justfile_directory()}}" regression-tier status

# =============================================================================
# 4. WAVE=1 RUN
# =============================================================================
# remote-executor SKILL.md's step 5 and CLAUDE.md's First-Failure Waveform
# Rerun: re-run the SAME representative scenario that VERIFY just ran, this
# time with signal-level waveform capture on (`make sim PATTERN=<n>
# WAVE=1`), Coverage still OFF. Never a blanket re-run of a whole suite --
# targeted, one pattern at a time, per CLAUDE.md ("never blanket-rerun the
# whole batch with waveform on just because some tests failed"). Same
# LSF_SIM job-submission path as VERIFY, so the same preflight dependency.
run pattern=pattern seed=seed queue=queue workdir=preflight_workdir license_server=license_server: (preflight queue workdir license_server)
    {{python}} "{{remote_exec}}" --cwd "{{sim_dir}}" --timeout {{run_timeout}} "make sim PATTERN={{pattern}} SEED={{seed}} WAVE=1 {{make_paths}} LSF_QUEUE={{queue}}"

# =============================================================================
# 5. FSDBREPORT
# =============================================================================
# The real Synopsys `fsdbreport` CLI, run on the Linux DV server where
# Verdi/VCS is installed (dv_harness/fsdb_report.py's own module docstring
# -- confirmed this Windows PC has no fsdbreport install). Confirmed real
# flag grammar (same docstring): `fsdbreport <fsdb> -bt <t0> -et <t1> -s
# <hier_path> [...] [-verilog|-csv|-of h] -o <outfile>` -- file path first,
# then flags. bt/et/signals/out are required arguments here rather than
# guessed defaults, since no default time window or signal list is a real,
# confirmed convention for this project. Never a remote job submission
# (post-processing an FSDB that already exists), so no preflight dependency.
fsdbreport fsdb bt et signals out fmt="-verilog":
    {{python}} "{{remote_exec}}" --cwd "{{sim_dir}}" "fsdbreport {{fsdb}} -bt {{bt}} -et {{et}} -s {{signals}} {{fmt}} -o {{out}}"

# =============================================================================
# Composite pipeline (BUILD -> VERIFY -> WAVE=1 RUN, PUSH/FSDBREPORT are
# separate because they need directory/signal arguments this composite
# cannot guess). CONFIRMED LIVE (just --dry-run pipeline ...): `just`
# deduplicates identical dependency invocations within one run, so
# build/verify/run's three `preflight` dependencies (same queue/workdir/
# license_server here) resolve to ONE real preflight check, not three --
# `just build`/`just verify` run standalone still each perform their own.
# =============================================================================
pipeline pattern=pattern seed=seed queue=queue workdir=preflight_workdir license_server=license_server: (build queue workdir license_server) (verify pattern seed queue workdir license_server) (run pattern seed queue workdir license_server)
    @echo "pipeline done: build -> verify -> run for PATTERN={{pattern}} SEED={{seed}}. Run 'just fsdbreport' on the resulting FSDB next."
