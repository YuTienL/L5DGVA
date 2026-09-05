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
- resolve_transport() (2026-09-04) is what actually CHOOSES between the two
  above for a given deployment, on real probe evidence (a READY persistent
  relay for the configured VCHOST/VCHOP hop; lmutil/bqueues actually on
  PATH), and reports "none available" rather than guessing. Without it the
  runners were injectable but nothing shipped ever injected one -- see its
  own comment block for the full reasoning.
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

import os
import re
import shlex
import shutil
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


# --- transport RESOLUTION (which of the two real runners applies here) ------
#
# WHY THIS EXISTS (2026-09-04, harness-reliability gap close): both runners
# above were real and both were injectable, but nothing in the shipped
# `dv-harness` command paths ever CHOSE one. `engine.DVHarness.
# degradation_runner` defaulted to None (= LocalCommandRunner), and the only
# documented way to get the relay transport on a PC-side REMOTE_EXECUTION
# deployment was for a human to hand-write Python assigning the attribute --
# which meant the DEGRADED mode's license-full / farm-congested triggers were
# structurally unreachable in normal operation on this project's own actual
# deployment shape, however correct their implementation was.
#
# The resolution is deliberately EVIDENCE-BASED, never optimistic. "auto"
# arms a transport only when a real probe confirms one is genuinely usable
# here (a READY relay info file for the configured VCHOST/VCHOP hop, or
# lmutil+bqueues actually present on PATH). When neither is confirmed it
# resolves to "none" and NOTHING is armed -- because turning "command not
# found" into a DEGRADED verdict is precisely the fabricated conclusion
# CLAUDE.md's Evidence Truth Rule forbids, and is the exact reason
# `probe_resources` was made opt-in in the first place (see degradation.py's
# module docstring). An explicit "local"/"remote_relay" request from a human
# is honoured as stated -- that is what explicit means -- but the probe still
# runs and its real result is recorded in `evidence` so a deployment that
# asked for a transport it does not actually have can see that in
# `dv-harness status` rather than discovering it as a mystery FAIL.

TRANSPORT_AUTO = "auto"
TRANSPORT_LOCAL = "local"
TRANSPORT_REMOTE_RELAY = "remote_relay"
TRANSPORT_OFF = "off"
#: Resolved-only value: asked for auto, no real transport could be confirmed.
TRANSPORT_NONE = "none"
#: What a caller (config key / CLI flag) may REQUEST.
TRANSPORT_CHOICES = (TRANSPORT_AUTO, TRANSPORT_LOCAL, TRANSPORT_REMOTE_RELAY, TRANSPORT_OFF)

#: Commands the local transport must actually be able to find for the
#: license/queue probes to mean anything. Names, not paths -- the license
#: binary is overridable via PreflightConfig.lmutil_path.
_LOCAL_REQUIRED_COMMANDS = ("lmutil", "bqueues")


@dataclass
class TransportDecision:
    """The real, inspectable answer to 'which transport applies here, and on
    what evidence'. `runner` is the live object to inject; every other field
    exists so the decision can be surfaced verbatim (`dv-harness status`)
    instead of being an invisible internal branch."""
    requested: str
    resolved: str          # TRANSPORT_LOCAL | TRANSPORT_REMOTE_RELAY | TRANSPORT_OFF | TRANSPORT_NONE
    available: bool
    reason: str
    evidence: Dict[str, object] = field(default_factory=dict)
    runner: Optional[Runner] = None

    def to_dict(self) -> dict:
        """Serialisable view -- deliberately omits `runner` (a live callable)."""
        return {"requested": self.requested, "resolved": self.resolved,
                "available": self.available, "reason": self.reason,
                "evidence": self.evidence}


def _probe_relay(env: Dict[str, str], relay_probe=None) -> Dict[str, object]:
    """Real readiness evidence for RemoteRelayCommandRunner: is a VCHOST/VCHOP
    hop configured, and does the persistent relay's own info file exist and
    parse? Uses tools/remote/remote_exec.py's read_relay_info() -- the same
    function RemoteRelayCommandRunner itself calls -- so this can never claim
    a relay is ready that the runner would then find missing. Never starts,
    reconnects, or authenticates anything (that stays a human/CLAUDE.md-gated
    action, per 'Remote Linux Execution (Persistent Relay)')."""
    vchost, vchop = env.get("VCHOST", ""), env.get("VCHOP", "")
    if not vchost or not vchop:
        return {"ready": False, "detail": "VC_HOST_HOP_NOT_CONFIGURED",
                "vchost_set": bool(vchost), "vchop_set": bool(vchop)}
    probe = relay_probe
    if probe is None:
        try:
            probe = _remote_exec_module().read_relay_info
        except Exception as e:  # noqa: BLE001 -- a missing/broken tools/remote is evidence, not a crash
            return {"ready": False, "detail": f"REMOTE_EXEC_UNAVAILABLE: {e}"}
    try:
        info = probe(vchost, vchop)
    except Exception as e:  # noqa: BLE001
        return {"ready": False, "detail": f"RELAY_PROBE_FAILED: {e}"}
    if not info:
        return {"ready": False, "detail": "RELAY_NOT_READY"}
    return {"ready": True, "detail": "RELAY_READY", "vchost": vchost, "vchop": vchop}


def _probe_local(lmutil_path: str, which=None) -> Dict[str, object]:
    """Real presence evidence for LocalCommandRunner: are the binaries the
    license/queue checks actually shell out to on PATH here? Presence is the
    only claim made -- this never runs them."""
    resolver = which or shutil.which
    wanted = [lmutil_path or "lmutil"] + [c for c in _LOCAL_REQUIRED_COMMANDS if c != "lmutil"]
    found = {cmd: resolver(cmd) for cmd in wanted}
    missing = [cmd for cmd, path in found.items() if not path]
    return {"ready": not missing, "found": {k: bool(v) for k, v in found.items()},
            "missing": missing,
            "detail": "LOCAL_COMMANDS_PRESENT" if not missing
                      else f"LOCAL_COMMANDS_MISSING: {', '.join(missing)}"}


def resolve_transport(requested: str = TRANSPORT_AUTO,
                       cfg: Optional[dict] = None,
                       env: Optional[Dict[str, str]] = None,
                       which=None,
                       relay_probe=None) -> TransportDecision:
    """Picks the real transport for this deployment and returns it together
    with the evidence the choice was made on.

    `cfg` may be the whole config dict or just its `preflight` block (same
    forgiving shape degradation._cfg() already accepts) -- only
    `lmutil_path` is read from it. `env`/`which`/`relay_probe` are injected
    exactly the way every other probe in this module is, so a test decides
    the whole answer without touching a real PATH or a real relay.
    """
    env = dict(os.environ if env is None else env)
    block = cfg or {}
    if isinstance(block, dict) and isinstance(block.get("preflight"), dict):
        block = block["preflight"]
    lmutil_path = (block or {}).get("lmutil_path", "lmutil") if isinstance(block, dict) else "lmutil"

    req = (requested or TRANSPORT_AUTO).strip().lower()
    if req not in TRANSPORT_CHOICES:
        # A typo in config.json must fail toward "probe nothing", never
        # toward an unintended live probe of a real license server.
        return TransportDecision(requested=requested, resolved=TRANSPORT_NONE, available=False,
                                  reason=(f"unknown transport {requested!r}; expected one of "
                                          f"{', '.join(TRANSPORT_CHOICES)}. No probe transport armed."),
                                  evidence={"unknown_transport": requested})

    if req == TRANSPORT_OFF:
        return TransportDecision(requested=req, resolved=TRANSPORT_OFF, available=False,
                                  reason="transport explicitly disabled (off): no resource probing.",
                                  evidence={})

    if req == TRANSPORT_LOCAL:
        ev = _probe_local(lmutil_path, which=which)
        return TransportDecision(requested=req, resolved=TRANSPORT_LOCAL, available=True,
                                  reason=f"local transport explicitly requested ({ev['detail']}).",
                                  evidence={"local": ev}, runner=LocalCommandRunner())

    if req == TRANSPORT_REMOTE_RELAY:
        ev = _probe_relay(env, relay_probe=relay_probe)
        return TransportDecision(requested=req, resolved=TRANSPORT_REMOTE_RELAY, available=True,
                                  reason=f"remote relay transport explicitly requested ({ev['detail']}).",
                                  evidence={"relay": ev},
                                  runner=RemoteRelayCommandRunner(env.get("VCHOST") or None,
                                                                   env.get("VCHOP") or None))

    # auto: relay first (a PC-side REMOTE_EXECUTION session is this
    # project's own real deployment shape, and a READY relay is positive
    # evidence that the REAL server is reachable), then local, then nothing.
    relay_ev = _probe_relay(env, relay_probe=relay_probe)
    if relay_ev.get("ready"):
        return TransportDecision(requested=req, resolved=TRANSPORT_REMOTE_RELAY, available=True,
                                  reason=("auto: persistent relay is READY for the configured "
                                          "VCHOST/VCHOP hop -- probing the real DV server through it."),
                                  evidence={"relay": relay_ev},
                                  runner=RemoteRelayCommandRunner(env.get("VCHOST") or None,
                                                                   env.get("VCHOP") or None))
    local_ev = _probe_local(lmutil_path, which=which)
    if local_ev.get("ready"):
        return TransportDecision(requested=req, resolved=TRANSPORT_LOCAL, available=True,
                                  reason=("auto: running where the real license/scheduler binaries "
                                          "exist on PATH -- probing locally."),
                                  evidence={"relay": relay_ev, "local": local_ev},
                                  runner=LocalCommandRunner())
    return TransportDecision(
        requested=req, resolved=TRANSPORT_NONE, available=False,
        reason=("auto: no usable probe transport here -- "
                f"relay: {relay_ev['detail']}; local: {local_ev['detail']}. "
                "Resource probing stays OFF rather than reading a missing binary as a "
                "full license or a jammed farm."),
        evidence={"relay": relay_ev, "local": local_ev})


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


def parse_license_availability(stdout: str, features: Optional[List[str]] = None) -> dict:
    """Public wrapper over the SAME `_parse_lmstat_output()` `check_license()`
    itself uses to reach its verdict.

    Exists so a caller that needs the measured issued/in-use COUNTS -- rather
    than the PASS/FAIL verdict those counts produced -- reads them with the
    identical parse instead of re-parsing `lmstat` output or scraping the
    check's formatted `detail` string. `loop_budget.pressure_from_checks()` is
    the first such caller: section 92's deferral decision lives in the band
    BETWEEN "plenty" and "fully checked out", which the verdict alone cannot
    express. `features` defaults to no required-feature list, since a caller
    asking for headroom is asking about whatever features the server reported,
    not about a specific one being present."""
    return _parse_lmstat_output(stdout or "", list(features or []))


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
    # The PASS path carries the raw lmstat output too (the FAIL paths above
    # always did). A PASS verdict means "not fully checked out", which does not
    # say HOW MUCH headroom is left -- and section 92's deferral decision lives
    # exactly in that band. Carrying the real output lets a reader re-derive the
    # counts through parse_license_availability() instead of scraping `detail`.
    return CheckOutcome(name, "PASS", detail, command=cmd, evidence=res.stdout[:2000])


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
