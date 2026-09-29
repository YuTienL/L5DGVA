# lmstat + scheduler preflight gate, and the Preflight/Resource Guard Agent (2026-09-03)

## Scope

Highest-priority workstream from the user's own spec (verbatim, Traditional Chinese):
"lmstat + scheduler preflight -- 這個我會放到最高優先。bsub / sbatch 前先做 license、
queue、host、disk、workdir、EDA env 檢查。沒過就 BLOCKED，不派 job。" This closes it:
a real, callable preflight module wired into the one real job-submission call site so a
BLOCKED result genuinely prevents `bsub`, plus the new Preflight/Resource Guard Agent
that documents and invokes it. The Audit/Change Governance Agent named in the same spec
paragraph is explicitly a separate workstream, not built here.

## What was built

### `dv_harness/preflight.py` (new module)

Six real, structured checks, each returning a `CheckOutcome` (`name`/`status`/`detail`/
`command`/`evidence` -- never a bare boolean):

1. **eda_license** -- real `lmutil lmstat -a -c <server>`; requires the license server
   report `UP` and every configured feature have `in_use < issued` headroom. An
   unconfigured `license_server` FAILs by default (`require_license_configured=True`) --
   an unconfirmed condition is never silently treated as fine.
2. **lsf_queue_health** -- real `bqueues <queue>`; requires the queue exist and report
   `Open:Active` (same `Open:Active` criterion, same `bqueues` command this session
   already used for the real `vcs` queue).
3. **host_reachability** -- runs `hostname` over the same transport a submission would
   use; a real reply is the reachability evidence.
4. **disk_space** -- real `df -Pk <workdir>`; available space vs. a configured minimum.
5. **workdir** -- real `test -d`/`test -w` against the real remote working directory.
6. **eda_env_vars** -- confirms the project's required EDA env vars
   (`VCS_HOME`/`UVM_HOME`/`VERDI_HOME`, from the real Makefile's own `$(error VCS_HOME is
   not set)`/`VERDI_HOME`-degrade logic) are genuinely set in the execution shell.

`run_preflight(cfg, runner)` combines all six: **any** FAIL -> `overall="BLOCKED"`; `SKIP`
(e.g. no workdir configured for a submission that doesn't need one) never blocks.

Transport is fully injected (`Runner = Callable[[cmd, timeout], CommandResult]`), never
assumed, mirroring `lsf_client.py`'s own real-vs-test seam:
- `LocalCommandRunner` -- real `subprocess.run()`, the default, correct when
  `dv_harness` runs server-side on the Linux DV server (where `bsub`/`bqueues`/`lmutil`/
  `df` are natively on PATH -- same assumption `lsf_client.discover_live_jobs()` already
  states explicitly).
- `RemoteRelayCommandRunner` -- routes through the already-sanctioned, credential-free
  persistent relay (`tools/remote/remote_exec.py`'s `read_relay_info()`/
  `send_request()`), the identical mechanism `dv_harness/knowledge_center.py`'s
  `_invoke()` already uses. For a Windows-PC-side session in REMOTE_EXECUTION mode.
- Unit tests inject a third, pure-mock `Runner` fed with **real captured output** from
  this session's own live checks (see "Real preflight-check output obtained" below) --
  never a live call against production infrastructure from a test.

`config_from_dict()` builds a `PreflightConfig` from `.dv-harness/config.json`'s new
`preflight` block plus per-submission overrides (queue/workdir), matching the forward-
compatible unknown-key-tolerant pattern `lsf_client.load_job_state()` already uses.

### `dv_harness/lsf_client.py` (wired, not new)

- `PreflightBlockedError(RuntimeError)` -- carries the full `PreflightResult`; a distinct
  class from `LsfUnavailableError` on purpose (one means "LSF unreachable", the other
  means "LSF is reachable but the gate refused this job") -- confirmed by a real test
  that neither is a subclass of the other.
- `bsub_submit_with_preflight(...)` -- the real, GATED entry point. Runs
  `preflight.run_preflight()` first; **`bsub_submit()` is never called at all** when the
  result is `BLOCKED`. `skip_preflight=True` is an explicit, audited bypass, never a
  silent default. `bsub_submit()` itself is left unchanged/ungated (existing tests and
  any caller with its own reason to bypass still work).

### `dv_harness/cli.py` (wired)

- `dv-harness lsf-submit` now calls `bsub_submit_with_preflight()` instead of
  `bsub_submit()` directly, builds its `PreflightConfig` from `h.cfg["preflight"]`
  overridden by the submission's own `--queue`/`--run-dir`, adds `--skip-preflight`
  (explicit escape hatch), and on `PreflightBlockedError` prints
  `{"error": "PREFLIGHT_BLOCKED", "preflight": <full result>}` and exits 1 -- `bsub` is
  never attempted.
- New standalone `dv-harness preflight [--queue] [--workdir] [--license-server]
  [--remote]` command -- runs the gate without submitting anything (for the new agent, or
  a human, to check before even building a `bsub` command line); exits 1 on `BLOCKED`.

### `dv_harness/config.py` (new `preflight` config block)

Added to `DEFAULT_CONFIG`, same "never guessed/hardcoded" convention as
`knowledge_center.remote_root`/`rtl_protection.protected_paths`: `queue` defaults to the
real project-wide `"vcs"` default (matching the Makefile's own `LSF_QUEUE ?= vcs`),
`license_server`/`workdir` default empty (a project must fill in its own real values),
`required_env_vars` defaults to `["VCS_HOME", "UVM_HOME", "VERDI_HOME"]`. The existing
shallow per-top-level-key merge in `load_config()` means any pre-existing project's
`.dv-harness/config.json` picks up this new block automatically with no migration step.

### `.claude/agents/preflight-resource-guard-agent.md` (new agent)

Matches `build-agent.md`/`regression-agent.md`'s frontmatter/structure convention exactly
(`tools: Read, Grep, Glob, PowerShell, Skill, Agent`, `disallowedTools: Edit, Write`,
`model: inherit`, a `skills:` list referencing the existing `CORE/remote-intake` and
`CORE/lsf-regression-monitor` skills). Documents the six real checks, the real
project-specific tcsh/`$?VAR`/credential-filter/`lmutil`-vs-`lmstat` gotchas found live
this session (see below), and an explicit "never fabricate a check result / never
hardcode infrastructure values / never treat `--skip-preflight` as routine" section.
`.claude/agents/ROSTER.md` updated (20 -> 21 real agents, alphabetically inserted).

## Tests

- `dv_harness_tests/test_preflight.py` (38 tests) -- every check function against both
  synthetic and **real captured** `bqueues`/`lmstat`/`df`/env-check output (see below);
  `PreflightConfig`/`config_from_dict` behavior; the aggregate gate (all-PASS,
  single-failure-blocks-everything, and the exact real 2026-09-03 scenario reproduced:
  license/queue/host/disk/workdir all real-PASS but env vars real-UNSET -> BLOCKED);
  `RemoteRelayCommandRunner`'s three real code paths (not-configured/relay-down/success,
  via a mocked `remote_exec` module); `LocalCommandRunner` against real local
  subprocesses (a real nonexistent-binary failure and a real Python subprocess success).
- `dv_harness_tests/test_preflight_lsf_wiring.py` (6 tests) -- confirms `bsub_submit()` is
  never called on `BLOCKED`, is called unchanged on `PASS`, `skip_preflight=True` really
  bypasses the gate, config/runner pass-through, and the two exception classes'
  independence.
- `dv_harness_tests/test_cli_preflight.py` (5 tests) -- real-subprocess CLI tests, same
  style as `test_cli_lsf_auto_kill_scan.py`: a fresh project with no license server
  configured and no real `bqueues`/`lmutil`/`bsub` on this dev machine's PATH produces a
  real (not mocked) `BLOCKED`/`PREFLIGHT_BLOCKED` result; `--license-server` really flows
  into the built command; `--skip-preflight` really flips the failure mode from
  `PREFLIGHT_BLOCKED` to `LSF_UNAVAILABLE`, proving the gate was actually bypassed (and no
  job-state file is ever written when blocked).

All 49 new tests pass. Full existing suite run in parallel for regression (see final
status below this report's own completion).

## Real preflight-check output obtained against the actual remote server

The persistent relay (`VCHOST=vchost-b VCHOP=host-c`) was already `READY` this session, so
every check below was run for real via `python tools/remote/remote_exec.py`, never
fabricated:

| Check | Real command | Real result |
|---|---|---|
| Queue health | `bqueues vcs` | `vcs 30 Open:Active - - - - 12 0 12 0` -- **PASS** (real, currently 12 RUN) |
| Host reachability | `hostname` | `host-c` -- **PASS** |
| Workdir | `test -d/-w /home/svcacct/DV/UVM/USB/usb_uvm/sim` | `DIR_EXISTS` / `DIR_WRITABLE` -- **PASS** |
| Disk space | `df -Pk /home/svcacct/DV/UVM/USB/usb_uvm/sim` | 1,659,650,752 KB (~1.58 TiB) available, 70% used -- **PASS** |
| EDA license | `lmutil lmstat -a -c 2900@host-a` (real server, discovered from `/eda/sunplus/modulefiles/synopsys/vcs/.common`'s `SNPSLMD_LICENSE_FILE` default) | `host-a: license server UP (MASTER) v10.8`, `snpslmd: UP v11.19`; `VCSRuntime`/`VCSCompiler`: 99 issued, 0 in use -- **PASS** |
| EDA env vars | `if ($?VCS_HOME) ...` (tcsh `$?VAR` syntax) for `VCS_HOME`/`UVM_HOME`/`VERDI_HOME`/`DESIGNWARE_HOME` | all four **UNSET** in the relay's persistent shell -- **FAIL** |

**Real overall verdict right now, against the real server: BLOCKED** (on `eda_env_vars`
only -- every other check is a real, live PASS). This is an honest, expected result, not a
bug: the persistent relay's shell never ran the project's `module load synopsys/vcs/...`
EDA setup step, so `VCS_HOME`/`UVM_HOME`/`VERDI_HOME`/`DESIGNWARE_HOME` are genuinely
unset in that exact shell. A real job submission through that same shell would fail for
the same reason -- which is exactly what this gate exists to catch before wasting a farm
slot on it, not a false positive.

Notable real infrastructure findings surfaced along the way (useful beyond this task):
- `lmstat` itself is not on PATH; the real binary is `/eda/sunplus/bin/lmutil` (invoke
  as `lmutil lmstat ...`).
- The real Synopsys VCS/Verdi license server is `2900@host-a` (`SNPSLMD_LICENSE_FILE`,
  from the real `synopsys/vcs` modulefile) -- `host-a` matches CLAUDE.md's own example SSH
  machine name, cross-confirming this is the project's real infrastructure, not a
  coincidence.
- This server's real remote login shell is **tcsh** -- a bare `$VAR` reference to an
  unset variable is a hard tcsh error ("VCS_HOME: Undefined variable."), which is why
  `preflight.py`'s env-var check is built around `$?VAR`, never `echo $VAR`.
- The persistent relay's own credential-inspection filter denies any bare
  `printenv`/`env`/`set`/`export` command outright (confirmed live: a plain
  `printenv VCS_HOME` came back `CREDENTIAL_INSPECTION_DENIED`) -- `preflight.py`'s
  env-var check deliberately avoids all four as a bare command on any shell.
- A default/unscoped `lmutil lmstat -a` on this server resolves to a **different**
  license pool entirely (Xilinx/Vivado, server `igs020`) -- confirming why
  `PreflightConfig.license_server` must be explicit/configured rather than left to
  whatever `lmutil`'s own default search order happens to find.

## Gaps / follow-ups (explicitly out of this task's scope)

- The Audit/Change Governance Agent from the same spec paragraph is a separate
  workstream, not built here.
- No project-wide `module load synopsys/vcs/<version>` step is currently run
  automatically before a real submission -- this task's gate correctly BLOCKS on that
  today; wiring an actual env-setup step is a separate, real infra decision for the user
  (not something to script autonomously against a shared EDA farm server).
- `.dv-harness/config.json`'s `preflight.license_server`/`workdir` are intentionally left
  empty in the shipped `DEFAULT_CONFIG` (never hardcoded for other projects/servers); this
  project's own real values (`2900@host-a`, `/home/svcacct/DV/UVM/USB/usb_uvm/sim`) are
  documented here and in the agent file, not baked into the generic library default.
