"""dv_harness/preflight.py -- lmstat + scheduler preflight gate.

L5 requirement (2026-09-03 user spec, highest-priority workstream): BEFORE
any bsub/sbatch job submission, run a fixed set of BLOCKING checks -- EDA
license availability, LSF/Slurm queue health, target host reachability,
disk space on the real remote working directory, workdir existence/
writability, and required EDA environment variables. Any FAIL means the
overall result is BLOCKED, never a warning-only degrade ("沒過就 BLOCKED，
不派 job" -- see the user's own spec). See lsf_client.bsub_submit_with_preflight()
for where a BLOCKED PreflightResult genuinely prevents a real `bsub` call.

Every check returns a structured CheckOutcome (name/status/detail/command/
evidence) -- never a bare boolean -- so a BLOCKED PreflightResult always
carries enough detail for a human or an agent to see exactly which real
condition failed and why.

TRANSPORT (fully injected, never assumed -- same design principle
lsf_client.py and tools/remote/remote_exec.py already establish):
- LocalCommandRunner: real `subprocess.run()`. Correct default when
  dv_harness itself runs server-side on the Linux DV server, where bsub/
  bjobs/bqueues/lmutil/df are natively on PATH -- see
  lsf_client.discover_live_jobs()'s own docstring for the identical
  transport assumption this mirrors.
- RemoteRelayCommandRunner: routes each check command through the
  already-sanctioned, credential-free persistent relay
  (tools/remote/remote_exec.py's read_relay_info()/send_request()) -- the
  exact mechanism dv_harness/knowledge_center.py's _invoke() already uses.
  Correct when a Windows-PC-side Claude Code session in REMOTE_EXECUTION
  mode (see CLAUDE.md's Execution Mode Gate) needs to preflight-check the
  real server before telling it to submit a job. Never spawns its own
  authenticated subprocess and never reads VCPW.
- dv_harness_tests/test_preflight.py injects a third, pure-mock Runner
  built from REAL captured lmstat/bqueues/df/env-check output (gathered
  2026-09-03 against the real project license server/queue/workdir over
  an already-READY relay -- see .work/governance-preflight-report.md) --
  this module itself never talks to a live license/scheduler server in a
  test.

ENV-VAR CHECK SHELL SYNTAX (real finding, 2026-09-03): this project's real
remote DV server's login shell is tcsh (confirmed live: `echo $0` ->
`-tcsh`), where referencing an unset variable via `$VAR` is a hard error
("VCS_HOME: Undefined variable."), not an empty string -- so the env-var
presence check below is built with `$?VAR` (csh/tcsh "is this variable
set" test), never a bare `$VAR`/`echo $VAR`. It also deliberately never
uses `printenv`/`env`/`set`/`export` as a bare command -- the persistent
relay's own credential-inspection filter
(tools/remote/remote_relay.py's `_CREDENTIAL_INSPECTION_PATTERNS`) denies
those outright (confirmed live: a `printenv VCS_HOME` request came back
`CREDENTIAL_INSPECTION_DENIED`), regardless of which specific variable
name follows.
"""
from __future__ import annotations

import re
import shlex
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Callable, Dict, List, Optional

# --- transport-neutral result/config/outcome types --------------------------


@dataclass
class CommandResult:
    """The one shape every Runner must return, regardless of transport --
    mirrors the fields tools/remote/remote_relay.py's own 'run' op response
    already uses (ok/exit_code/stdout/error), so RemoteRelayCommandRunner
    below is close to a pass-through."""
    ok: bool
    exit_code: Optional[int] = None
    stdout: str = ""
    stderr: str = ""
    error: Optional[str] = None


# A Runner takes the shell command text and a timeout (seconds) and returns
# a CommandResult. Every check function below only ever calls a Runner --
# never subprocess/socket directly -- so tests can inject a pure mock.
Runner = Callable[[str, int], CommandResult]


@dataclass
class CheckOutcome:
    name: str
    status: str  # "PASS" | "FAIL" | "SKIP"
    detail: str
    command: Optional[str] = None
    evidence: Optional[str] = None  # raw stdout/stderr, truncated -- real output, never fabricated


@dataclass
class PreflightConfig:
    queue: str = "vcs"  # this project's real confirmed default LSF queue --
    # see dv_harness/uvm_generator/templates/sim_scripts/Makefile's
    # `LSF_QUEUE ?= vcs` and its own `bqueues -l vcs` precedent.
    workdir: str = ""
    host: Optional[str] = None
    required_env_vars: List[str] = field(
        default_factory=lambda: ["VCS_HOME", "UVM_HOME", "VERDI_HOME"])
    min_free_disk_gb: float = 20.0
    license_server: str = ""  # e.g. "2900@host-a" -- "" means "not configured"
    license_features: List[str] = field(default_factory=lambda: ["VCSRuntime"])
    lmutil_path: str = "lmutil"
    shell: str = "csh"  # "csh"/"tcsh" or "sh" -- which env-var-presence syntax to build
    require_license_configured: bool = True  # an unconfigured license check
    # FAILs (blocks) by default rather than silently passing -- the whole
    # point of a preflight GATE is that an unconfirmed condition is never
    # treated as "fine". Set False only for a deployment that has
    # deliberately decided license availability is out of scope for it.


_PREFLIGHT_CONFIG_FIELDS = set(PreflightConfig.__dataclass_fields__.keys())


def config_from_dict(d: Optional[dict] = None, **overrides) -> PreflightConfig:
    """Builds a PreflightConfig from a plain dict (e.g. config.json's
    `preflight` block) plus explicit keyword overrides (e.g. a CLI's
    --queue/--run-dir for THIS submission) -- overrides win. Unknown keys
    in `d` are silently ignored (same forward-compatible pattern
    lsf_client.load_job_state() already uses for JobState), so an older
    config.json missing a newer field just gets that field's dataclass
    default, and a caller can pass extra config.json bookkeeping keys
    (e.g. "configured_by") without this raising a TypeError."""
    merged: Dict[str, object] = dict(d or {})
    for k, v in overrides.items():
        if v is not None:
            merged[k] = v
    kwargs = {k: v for k, v in merged.items() if k in _PREFLIGHT_CONFIG_FIELDS}
    return PreflightConfig(**kwargs)


@dataclass
class PreflightResult:
    overall: str  # "PASS" | "BLOCKED"
    checks: List[CheckOutcome]
    blocked_on: List[str]

    def to_dict(self) -> dict:
        return {
            "overall": self.overall,
            "blocked_on": self.blocked_on,
            "checks": [asdict(c) for c in self.checks],
        }


# --- real runners -------------------------------------------------------


class LocalCommandRunner:
    """Real local `subprocess.run()`. The correct default transport when
    dv_harness itself runs server-side on the Linux DV server -- bsub/
    bjobs/bqueues/lmutil/df are natively on PATH there, exactly the
    assumption lsf_client.py's own bsub_submit()/discover_live_jobs()
    already make (see the latter's docstring)."""

    def __call__(self, cmd: str, timeout: int = 60) -> CommandResult:
        try:
            proc = subprocess.run(cmd, shell=True, capture_output=True,
                                   text=True, timeout=timeout)
        except FileNotFoundError as e:
            return CommandResult(ok=False, error=f"COMMAND_NOT_FOUND: {e}")
        except subprocess.TimeoutExpired as e:
            return CommandResult(ok=False, error=f"TIMEOUT: {e}")
        return CommandResult(ok=proc.returncode == 0, exit_code=proc.returncode,
                              stdout=proc.stdout or "", stderr=proc.stderr or "")


def _remote_exec_module():
    """Imports tools/remote/remote_exec.py's read_relay_info()/
    send_request() -- identical helper to
    dv_harness/knowledge_center.py's own `_remote_exec_module()` (not a
    package import: tools/remote/ has no __init__.py)."""
    remote_dir = str(Path(__file__).resolve().parents[1] / "tools" / "remote")
    if remote_dir not in sys.path:
        sys.path.insert(0, remote_dir)
    import remote_exec  # type: ignore
    return remote_exec


class RemoteRelayCommandRunner:
    """Routes each check command through the already-sanctioned,
    credential-free persistent relay (tools/remote/remote_exec.py) -- the
    same mechanism dv_harness/knowledge_center.py's `_invoke()` already
    uses. Correct transport for a Windows-PC-side Claude Code session in
    REMOTE_EXECUTION mode that needs to preflight-check the real Linux DV
    server before telling it to submit a job. Never spawns its own
    authenticated subprocess and never reads VCPW; cleanly reports
    RELAY_NOT_READY/VC_HOST_HOP_NOT_CONFIGURED rather than attempting to
    start or reconnect a relay itself (that stays a human/CLAUDE.md-gated
    action, per "Remote Linux Execution (Persistent Relay)")."""

    def __init__(self, vchost: Optional[str] = None, vchop: Optional[str] = None):
        import os
        self.vchost = vchost or os.environ.get("VCHOST", "")
        self.vchop = vchop or os.environ.get("VCHOP", "")

    def __call__(self, cmd: str, timeout: int = 60) -> CommandResult:
        if not self.vchost or not self.vchop:
            return CommandResult(ok=False, error="VC_HOST_HOP_NOT_CONFIGURED")
        remote_exec = _remote_exec_module()
        info = remote_exec.read_relay_info(self.vchost, self.vchop)
        if info is None:
            return CommandResult(ok=False, error="RELAY_NOT_READY")
        try:
            resp = remote_exec.send_request(
                info["host"], info["port"],
                {"token": info["token"], "op": "run", "cmd": cmd, "timeout": timeout},
                timeout=timeout,
            )
        except Exception as e:  # noqa: BLE001 -- any transport failure reported, never masked
            return CommandResult(ok=False, error=f"RELAY_UNREACHABLE: {e}")
        if not resp.get("ok"):
            return CommandResult(ok=False, exit_code=resp.get("exit_code"),
                                  error=resp.get("error") or "RELAY_RUN_FAILED")
        return CommandResult(ok=True, exit_code=resp.get("exit_code"),
                              stdout=resp.get("stdout") or "")


# --- individual checks (pure parse helpers + thin runner-calling wrappers) --

_LICENSE_SERVER_UP_RE = re.compile(r"license server\s+UP\b", re.IGNORECASE)
_LICENSE_FEATURE_RE = re.compile(
    r"Users of ([\w.\-]+):\s*\(Total of (\d+) licenses? issued;\s*"
    r"Total of (\d+) licenses? in use\)",
    re.IGNORECASE,
)


def _parse_lmstat_output(stdout: str, features: List[str]) -> dict:
    server_up = bool(_LICENSE_SERVER_UP_RE.search(stdout))
    found: Dict[str, Dict[str, int]] = {}
    for m in _LICENSE_FEATURE_RE.finditer(stdout):
        found[m.group(1)] = {"issued": int(m.group(2)), "in_use": int(m.group(3))}
    missing = [f for f in features if f not in found]
    return {"server_up": server_up, "features": found, "missing_features": missing}


def check_license(runner: Runner, cfg: PreflightConfig, timeout: int = 60) -> CheckOutcome:
    name = "eda_license"
    if not cfg.license_server:
        if cfg.require_license_configured:
            return CheckOutcome(
                name, "FAIL",
                "No license server configured (PreflightConfig.license_server is empty) "
                "-- cannot verify EDA license availability before submission.")
        return CheckOutcome(name, "SKIP",
                             "License check not configured; skipped per "
                             "require_license_configured=False.")
    cmd = f"{cfg.lmutil_path} lmstat -a -c {cfg.license_server}"
    res = runner(cmd, timeout)
    if not res.ok:
        return CheckOutcome(name, "FAIL",
                             f"lmstat command failed: {res.error or ('exit_code=' + str(res.exit_code))}",
                             command=cmd, evidence=(res.stdout or res.stderr)[:2000])
    parsed = _parse_lmstat_output(res.stdout, cfg.license_features)
    if not parsed["server_up"]:
        return CheckOutcome(name, "FAIL",
                             f"license server {cfg.license_server} not reported UP",
                             command=cmd, evidence=res.stdout[:2000])
    if parsed["missing_features"]:
        return CheckOutcome(name, "FAIL",
                             f"license feature(s) not found in lmstat output: "
                             f"{parsed['missing_features']}",
                             command=cmd, evidence=res.stdout[:2000])
    starved = [f for f, v in parsed["features"].items() if v["in_use"] >= v["issued"]]
    if starved:
        return CheckOutcome(name, "FAIL",
                             f"license feature(s) fully checked out (starvation): {starved}",
                             command=cmd, evidence=res.stdout[:2000])
    detail = "; ".join(
        f"{f}: {v['issued'] - v['in_use']}/{v['issued']} available"
        for f, v in parsed["features"].items())
    return CheckOutcome(name, "PASS", detail, command=cmd)


def _parse_bqueues_output(stdout: str, queue: str) -> Optional[dict]:
    for line in stdout.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("QUEUE_NAME"):
            continue
        parts = stripped.split()
        if len(parts) >= 3 and parts[0] == queue:
            return {"queue": parts[0], "status": parts[2]}
    return None


def check_queue_health(runner: Runner, cfg: PreflightConfig, timeout: int = 60) -> CheckOutcome:
    """Real precedent: this session already confirmed the real 'vcs' queue
    via `bqueues vcs` reporting `Open:Active` -- same command, same
    Open:Active criterion, per the user's spec ("這比單純提升便利性的工具更
    像真正的 L5 必要條件") and dv_harness/uvm_generator/templates/
    sim_scripts/Makefile's own `lsf_queues` target precedent."""
    name = "lsf_queue_health"
    cmd = f"bqueues {cfg.queue}"
    res = runner(cmd, timeout)
    if not res.ok:
        return CheckOutcome(name, "FAIL",
                             f"bqueues failed: {res.error or ('exit_code=' + str(res.exit_code))}",
                             command=cmd, evidence=(res.stdout or res.stderr)[:2000])
    row = _parse_bqueues_output(res.stdout, cfg.queue)
    if row is None:
        return CheckOutcome(name, "FAIL", f"queue '{cfg.queue}' not found in bqueues output",
                             command=cmd, evidence=res.stdout[:2000])
    status = row["status"]
    if "Open" in status and "Active" in status:
        return CheckOutcome(name, "PASS", f"queue '{cfg.queue}' status={status}", command=cmd)
    return CheckOutcome(name, "FAIL",
                         f"queue '{cfg.queue}' not Open:Active (status={status})",
                         command=cmd, evidence=res.stdout[:500])


def check_host_reachability(runner: Runner, cfg: PreflightConfig, timeout: int = 30) -> CheckOutcome:
    """`hostname` is run over the SAME transport a real job submission
    would use -- a successful reply IS the reachability evidence (no
    separate ping needed, and ICMP is frequently firewalled on farm
    hosts anyway). If cfg.host names a specific expected LSF submission
    host, the reply is also checked against it."""
    name = "host_reachability"
    cmd = "hostname"
    res = runner(cmd, timeout)
    if not res.ok:
        return CheckOutcome(name, "FAIL",
                             f"target host unreachable / command failed: "
                             f"{res.error or ('exit_code=' + str(res.exit_code))}",
                             command=cmd)
    lines = [l for l in res.stdout.strip().splitlines() if l.strip()]
    actual = lines[-1].strip() if lines else ""
    if cfg.host and actual and cfg.host != actual:
        return CheckOutcome(name, "FAIL",
                             f"reachable host '{actual}' does not match expected host '{cfg.host}'",
                             command=cmd, evidence=actual)
    return CheckOutcome(name, "PASS", f"target host reachable (hostname={actual or 'unknown'})",
                         command=cmd)


def _parse_df_output(stdout: str) -> Optional[dict]:
    lines = [l for l in stdout.splitlines() if l.strip()]
    if len(lines) < 2:
        return None
    parts = lines[1].split()
    if len(parts) < 6 and len(lines) >= 3:
        # a long filesystem name can push `df -P`'s numeric columns onto
        # their own wrapped line -- concatenate before re-splitting.
        parts = (lines[1] + " " + lines[2]).split()
    if len(parts) < 6:
        return None
    try:
        available_kb = int(parts[3])
    except (ValueError, IndexError):
        return None
    return {"available_kb": available_kb, "available_gb": available_kb / (1024 * 1024)}


def check_disk_space(runner: Runner, cfg: PreflightConfig, timeout: int = 30) -> CheckOutcome:
    name = "disk_space"
    if not cfg.workdir:
        return CheckOutcome(name, "SKIP", "no workdir configured; disk-space check skipped.")
    cmd = f"df -Pk {shlex.quote(cfg.workdir)}"
    res = runner(cmd, timeout)
    if not res.ok:
        return CheckOutcome(name, "FAIL",
                             f"df failed: {res.error or ('exit_code=' + str(res.exit_code))}",
                             command=cmd, evidence=(res.stdout or res.stderr)[:1000])
    parsed = _parse_df_output(res.stdout)
    if parsed is None:
        return CheckOutcome(name, "FAIL", "could not parse df output", command=cmd,
                             evidence=res.stdout[:1000])
    if parsed["available_gb"] < cfg.min_free_disk_gb:
        return CheckOutcome(name, "FAIL",
                             f"only {parsed['available_gb']:.1f}GB free at {cfg.workdir}, "
                             f"below required {cfg.min_free_disk_gb}GB",
                             command=cmd, evidence=res.stdout[:500])
    return CheckOutcome(name, "PASS",
                         f"{parsed['available_gb']:.1f}GB free at {cfg.workdir}", command=cmd)


def check_workdir(runner: Runner, cfg: PreflightConfig, timeout: int = 30) -> CheckOutcome:
    name = "workdir"
    if not cfg.workdir:
        return CheckOutcome(name, "SKIP", "no workdir configured; workdir check skipped.")
    wd = shlex.quote(cfg.workdir)
    cmd = f"test -d {wd} && echo DIR_EXISTS || echo DIR_MISSING; " \
          f"test -w {wd} && echo DIR_WRITABLE || echo DIR_NOT_WRITABLE"
    res = runner(cmd, timeout)
    out = res.stdout or ""
    if not res.ok and not out:
        return CheckOutcome(name, "FAIL",
                             f"workdir check command failed: "
                             f"{res.error or ('exit_code=' + str(res.exit_code))}", command=cmd)
    exists = "DIR_EXISTS" in out
    writable = "DIR_WRITABLE" in out
    if exists and writable:
        return CheckOutcome(name, "PASS", f"{cfg.workdir} exists and is writable", command=cmd)
    reasons = []
    if not exists:
        reasons.append("does not exist")
    if not writable:
        reasons.append("not writable")
    return CheckOutcome(name, "FAIL", f"{cfg.workdir}: {', '.join(reasons)}",
                         command=cmd, evidence=out[:500])


def _build_env_check_command(var_names: List[str], shell: str) -> str:
    """csh/tcsh branch uses `$?VAR` (real finding, see this module's
    docstring: a bare `$VAR` on an unset variable is a hard tcsh error on
    this project's real remote server, not an empty string). The sh/bash
    branch avoids `printenv`/`env`/`set`/`export` as a bare command
    (blocked outright by the persistent relay's own credential-inspection
    filter, confirmed live -- see this module's docstring), using a plain
    `[ -z "${VAR+x}" ]` presence test instead."""
    if shell in ("csh", "tcsh"):
        parts = []
        for v in var_names:
            parts.append(f"if ($?{v}) echo {v}_SET")
            parts.append(f"if (! $?{v}) echo {v}_UNSET")
        return "; ".join(parts)
    parts = [f'if [ -z "${{{v}+x}}" ]; then echo {v}_UNSET; else echo {v}_SET; fi'
             for v in var_names]
    return "; ".join(parts)


def check_env_vars(runner: Runner, cfg: PreflightConfig, timeout: int = 30) -> CheckOutcome:
    name = "eda_env_vars"
    if not cfg.required_env_vars:
        return CheckOutcome(name, "SKIP", "no required env vars configured.")
    cmd = _build_env_check_command(cfg.required_env_vars, cfg.shell)
    res = runner(cmd, timeout)
    out = res.stdout or ""
    if not res.ok and not out:
        return CheckOutcome(name, "FAIL",
                             f"env-var check command failed: "
                             f"{res.error or ('exit_code=' + str(res.exit_code))}", command=cmd)
    missing = [v for v in cfg.required_env_vars if f"{v}_SET" not in out]
    if missing:
        return CheckOutcome(name, "FAIL", f"required EDA env var(s) not set: {missing}",
                             command=cmd, evidence=out[:1000])
    return CheckOutcome(name, "PASS", f"all required env vars set: {cfg.required_env_vars}",
                         command=cmd)


# --- aggregate gate -------------------------------------------------------

_ALL_CHECKS = (
    check_license,
    check_queue_health,
    check_host_reachability,
    check_disk_space,
    check_workdir,
    check_env_vars,
)


def run_preflight(cfg: PreflightConfig, runner: Optional[Runner] = None) -> PreflightResult:
    """Runs every real check above and combines them into one gate verdict.
    ANY check FAIL -> overall BLOCKED (SKIP never blocks -- it means the
    check genuinely does not apply, e.g. no workdir was configured for
    this submission -- but a FAIL always does, per the user's own spec:
    "沒過就 BLOCKED，不派 job"). `runner` defaults to LocalCommandRunner()
    (the correct transport for dv_harness running server-side -- see this
    module's own docstring)."""
    if runner is None:
        runner = LocalCommandRunner()
    checks = [fn(runner, cfg) for fn in _ALL_CHECKS]
    blocked_on = [c.name for c in checks if c.status == "FAIL"]
    overall = "BLOCKED" if blocked_on else "PASS"
    return PreflightResult(overall=overall, checks=checks, blocked_on=blocked_on)
