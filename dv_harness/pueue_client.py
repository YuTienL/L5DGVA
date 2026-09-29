"""dv_harness/pueue_client.py -- Windows-PC-local task orchestration via pueue.

L5 requirement (2026-09-03 user spec, verbatim): "pueue -- 適合 PC/local
orchestration。但真正 farm workload 還是交給 bsub/sbatch。可理解為：Claude ->
pueue -> harness task -> LSF/Slurm". pueue sequences LOCAL, PC-side harness
steps (a local build/lint command, or a `tools/remote/remote_exec.py` call
that synchronously runs one remote command and returns) as a real dependency
chain. It deliberately never manages a real farm job's own lifecycle: the one
real `bsub`/`sbatch` submission always happens through
`dv_harness.lsf_client.bsub_submit_with_preflight()` -- invoked here as a
single pueue task's command string, exactly like every other step. Once that
task's underlying process exits, pueue's involvement with that job is over;
ongoing farm-job tracking stays with `dv_harness.regression_reporter`'s own
`lsf-watch-start` background monitor, never with pueue. This module never
constructs a `bsub`/`sbatch` command line itself -- every command string is
caller-supplied.

That last sentence used to be the ONLY thing keeping an un-gated farm
submission out of a pueue task: nothing stopped a caller handing `add()` a
bare `bsub -q vcs simv` string, which would have run a real submission with
`dv_harness/preflight.py`'s license/queue/host/disk/workdir/env gate never
consulted -- the exact "沒過就 BLOCKED，不派 job" rule
`lsf_client.bsub_submit_with_preflight()` enforces on every other path. It is
now enforced code: `assert_farm_submission_is_preflight_gated()` (below) runs
inside `add()`, so every task -- including every step of
`enqueue_harness_chain()` and every `dv-harness pueue add`/`pueue chain`
invocation -- is checked before it can be enqueued.

INSTALL: no winget/choco package exists for pueue as of this writing (both
searched live, 2026-09-03: `winget search pueue` / `choco search pueue` ->
zero hits). The real, official channel is Nukesor/pueue's own GitHub
Releases (https://github.com/Nukesor/pueue/releases) -- prebuilt
`pueue-x86_64-pc-windows-msvc.exe` / `pueued-x86_64-pc-windows-msvc.exe`
binaries, sha256-verified against the release's own published digests before
first use. See `.work/governance-pueue-notify-report.md` for the exact
download/verify transcript. This module does not perform that download
itself -- it only locates and drives an already-installed `pueue`/`pueued`.

SECURITY (real finding, 2026-09-03 -- read before changing add()): pueue's
CLIENT captures the FULL, unfiltered process environment of whichever
process invokes `pueue add`, and pueue's DAEMON persists that captured
environment, in PLAINTEXT, inside its own `state.json` on disk indefinitely
(until `pueue clean`/`pueue remove`). Confirmed live: a real `VCPW` value
already present in this session's own shell environment appeared verbatim in
`pueue status -j`'s per-task "envs" field the instant a task was added from
that shell. This directly conflicts with CLAUDE.md's SSH/Remote Transport
Connection Intake rule ("[the password] must never be written into any
evidence block, gate payload, state file, log, or long-term/native memory").
Every call into pueue below therefore NEVER passes the ambient environment
through unfiltered -- `_sanitize_env()` strips every credential-shaped key
first. This is the single most load-bearing design decision in this file;
do not bypass it by calling `pueue`/`pueued` directly from elsewhere with an
unsanitized environment.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

# --- environment sanitization (see module docstring's SECURITY section) ----

# Broad, case-insensitive denylist: any env var name CONTAINING one of these
# substrings is dropped before a `pueue add`/`pueue`-daemon-facing call is
# made. Deliberately over-inclusive (e.g. SSH_ASKPASS, a program PATH not a
# secret itself, still matches "PASS") -- a task command that genuinely
# needs one of these must receive it some other way (a config file, a
# relay already holding the credential server-side), never via pueue's own
# captured-env persistence.
_SENSITIVE_ENV_NAME_RE = re.compile(
    r"(PASS|PW\b|_PW$|SECRET|TOKEN|CREDENTIAL|APIKEY|API_KEY|PRIVATE_KEY|"
    r"COOKIE|AUTH)",
    re.IGNORECASE,
)


def _sanitize_env(env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Returns a COPY of `env` (default: os.environ) with every
    credential-shaped key removed. Never mutates the input mapping."""
    src = dict(env) if env is not None else dict(os.environ)
    return {k: v for k, v in src.items() if not _SENSITIVE_ENV_NAME_RE.search(k)}


# --- binary resolution -------------------------------------------------

DEFAULT_EXTRA_BIN_DIRS: List[str] = [str(Path.home() / "bin")]
# `~/bin` (portable across users via Path.home(), never a hardcoded personal
# path) is where this project's own tooling already lands manually-fetched
# Windows binaries with no winget/choco package -- verible's real
# `verible-*.exe` set was installed there this same session (2026-09-03,
# confirmed live via `ls`), and pueue.exe/pueued.exe follow the identical
# convention rather than inventing a second one.


def _resolve_binary(name: str, extra_dirs: Optional[Sequence[str]] = None) -> str:
    """shutil.which() first (respects whatever the real PATH says); falls
    back to each of `extra_dirs` (default DEFAULT_EXTRA_BIN_DIRS) for a
    `<name>.exe`/`<name>` file. Returns the bare `name` unresolved (never
    fabricates a fake success) if nothing is found -- the caller's own
    subprocess call then raises a real FileNotFoundError, exactly the
    honest failure mode preflight.py's LocalCommandRunner already uses for
    a missing binary."""
    found = shutil.which(name)
    if found:
        return found
    for d in (extra_dirs if extra_dirs is not None else DEFAULT_EXTRA_BIN_DIRS):
        for candidate_name in (f"{name}.exe", name):
            candidate = Path(d) / candidate_name
            if candidate.is_file():
                return str(candidate)
    return name


# --- config --------------------------------------------------------------


@dataclass
class PueueConfig:
    binary: str = "pueue"
    daemon_binary: str = "pueued"
    extra_bin_dirs: List[str] = field(default_factory=lambda: list(DEFAULT_EXTRA_BIN_DIRS))
    group: str = "dv_harness"  # default pueue group this project's tasks use,
    # keeping them visually/queryably separate from any unrelated task a
    # user may also run through the SAME shared local pueue daemon.


_PUEUE_CONFIG_FIELDS = set(PueueConfig.__dataclass_fields__.keys())


def config_from_dict(d: Optional[dict] = None, **overrides) -> PueueConfig:
    """Same forward-compatible pattern as preflight.config_from_dict() --
    unknown keys in `d` are ignored, explicit non-None overrides win."""
    merged: Dict[str, object] = dict(d or {})
    for k, v in overrides.items():
        if v is not None:
            merged[k] = v
    kwargs = {k: v for k, v in merged.items() if k in _PUEUE_CONFIG_FIELDS}
    return PueueConfig(**kwargs)


# --- process seams (injectable, mirrors preflight.py's Runner pattern) ----


@dataclass
class ProcResult:
    ok: bool
    returncode: Optional[int] = None
    stdout: str = ""
    stderr: str = ""
    error: Optional[str] = None


ProcRunner = Callable[[List[str], Dict[str, str], int], ProcResult]
DaemonStarter = Callable[[List[str], Dict[str, str]], None]


def _default_proc_runner(argv: List[str], env: Dict[str, str], timeout: int) -> ProcResult:
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=env)
    except FileNotFoundError as e:
        return ProcResult(ok=False, error=f"BINARY_NOT_FOUND: {e}")
    except subprocess.TimeoutExpired as e:
        return ProcResult(ok=False, error=f"TIMEOUT: {e}")
    return ProcResult(ok=proc.returncode == 0, returncode=proc.returncode,
                       stdout=proc.stdout or "", stderr=proc.stderr or "")


def _default_daemon_starter(argv: List[str], env: Dict[str, str]) -> None:
    # Detached fire-and-forget start -- pueued itself daemonizes
    # (--daemonize), so this Popen's own lifetime does not matter once it
    # has spawned; no output pipe is kept open (avoids the exact
    # regression_reporter.ensure_watcher_running() BrokenPipe/silent-
    # discard hazard already documented there for background children).
    subprocess.Popen(argv, env=env, stdin=subprocess.DEVNULL,
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class PueueError(RuntimeError):
    pass


# --- un-gated farm-submission guard ---------------------------------------
#
# See the module docstring's "Claude -> pueue -> harness task -> LSF/Slurm"
# spec: the ONE real farm submission in this repo goes through
# `lsf_client.bsub_submit_with_preflight()`, which runs
# `preflight.run_preflight()` (license/queue/host/disk/workdir/env) first and
# refuses to call `bsub_submit()` at all on BLOCKED. A pueue task carrying a
# raw `bsub`/`sbatch` would route around that gate entirely, so this guard
# refuses to enqueue one.

FARM_SUBMIT_COMMANDS = ("bsub", "sbatch")

# Shell separators that start a fresh command position within one task string.
_SEGMENT_SPLIT_RE = re.compile(r"[;|&()`\n]+")
# `FOO=bar bsub ...` -- a leading env assignment does not consume the command
# position, so keep walking past it.
_ENV_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
# Commands that RUN another command rather than being the command themselves.
# `remote_exec.py` is the load-bearing one: `python tools/remote/remote_exec.py
# "bsub -q vcs simv"` is exactly the pueue step shape this module's own
# `enqueue_harness_chain()` docstring recommends, and its real payload is the
# quoted string, not `python`.
_COMMAND_WRAPPERS = frozenset({
    "ssh", "nohup", "time", "env", "exec", "sudo", "xargs", "eval",
    "sh", "bash", "csh", "tcsh", "python", "python3", "py", "remote_exec.py",
})


def _basename(token: str) -> str:
    return token.replace("\\", "/").rsplit("/", 1)[-1]


def _farm_submit_hits(command: str) -> List[tuple]:
    """Returns [(token, segment), ...] -- each `bsub`/`sbatch` this command
    would actually EXECUTE, paired with the shell segment it runs in. The
    segment is kept (not just the token) so the gate below can look for a
    gated-entry-point marker in the SAME segment, rather than accepting
    `dv-harness lsf-submit x && bsub -q vcs y` because the marker appeared
    somewhere else in the string."""
    hits: List[tuple] = []
    for segment in _SEGMENT_SPLIT_RE.split(command or ""):
        wrapper_seen = False
        for raw in segment.split():
            token = raw.strip("\"'").lstrip("$")
            if not token:
                continue
            if _ENV_ASSIGNMENT_RE.match(token):
                continue
            name = _basename(token)
            if name in FARM_SUBMIT_COMMANDS:
                hits.append((name, segment))
                break
            if name in _COMMAND_WRAPPERS:
                wrapper_seen = True
                continue
            if token.startswith("-"):
                continue
            if not wrapper_seen:
                # This segment's real command is something else entirely.
                break
    return hits


def find_farm_submit_tokens(command: str) -> List[str]:
    """Returns the `bsub`/`sbatch` commands `command` would actually EXECUTE,
    in order, deduplicated -- not every occurrence of the substring. A token
    counts only in command position: first word of a shell segment, after a
    leading env assignment, or anywhere in a segment that already went through
    a wrapper (`ssh host bsub ...`, `python tools/remote/remote_exec.py "bsub
    ..."`). So `grep bsub sim.log` and `./rerun_bsub_failures.sh` are not
    matches, while `/usr/lsf/bin/bsub -q vcs simv` and `cd run && sbatch j.sh`
    are."""
    found: List[str] = []
    for token, _segment in _farm_submit_hits(command):
        if token not in found:
            found.append(token)
    return found


# The `dv-harness` subcommand whose handler calls
# lsf_client.bsub_submit_with_preflight() (dv_harness/cli.py).
GATED_SUBMIT_CLI_SUBCOMMAND = "lsf-submit"


def gated_submit_markers() -> tuple:
    """The real, preflight-gated submission entry points a task command may
    name, read off the LIVE code objects rather than copy-pasted strings --
    rename `lsf_client.bsub_submit_with_preflight` and this guard's accepted
    spelling follows it instead of silently going stale."""
    from . import lsf_client  # local import: keeps pueue import cost low
    return (GATED_SUBMIT_CLI_SUBCOMMAND,
            lsf_client.bsub_submit_with_preflight.__name__)


class UngatedFarmSubmissionError(RuntimeError):
    """Raised by `add()` when a task command would run a real `bsub`/`sbatch`
    without going through the preflight gate.

    Deliberately NOT a PueueError subclass, for the same reason
    `lsf_client.PreflightBlockedError` is deliberately not an
    `LsfUnavailableError`: a caller must never catch "pueue itself failed" and
    silently absorb "this harness refused to submit an un-gated farm job" as
    the same condition. Carries `.command`, `.tokens` and `.markers` so a
    report can name the offending token and the accepted route."""

    def __init__(self, command: str, tokens: Sequence[str], markers: Sequence[str]):
        self.command = command
        self.tokens = list(tokens)
        self.markers = list(markers)
        super().__init__(
            "UNGATED_FARM_SUBMISSION: pueue task command runs "
            f"{'/'.join(self.tokens)} directly, bypassing the "
            "license/queue/host/disk/workdir/env preflight gate "
            "(dv_harness/preflight.py). Submit through "
            f"`dv-harness {GATED_SUBMIT_CLI_SUBCOMMAND} ...` (or a script "
            "calling lsf_client.bsub_submit_with_preflight()) as the task "
            f"command instead. Refused command: {command!r}"
        )


def assert_farm_submission_is_preflight_gated(command: str) -> None:
    """Raises UngatedFarmSubmissionError if `command` would execute a raw
    `bsub`/`sbatch` whose own shell segment does not also name a gated entry
    point. Returns None (never a bool a caller could forget to check) when the
    command is fine.

    Honest limit: the acceptance test is a marker STRING in the same segment,
    so a command that merely writes `lsf-submit` next to a raw `bsub` (in a
    comment, say) is accepted. This guard stops the accident -- a task author
    reaching for `bsub` out of habit -- not a caller deliberately dressing one
    up to look gated; only the gate inside
    lsf_client.bsub_submit_with_preflight() can do that, and it is what the
    accepted route actually runs."""
    ungated = []
    markers = gated_submit_markers()
    for token, segment in _farm_submit_hits(command):
        if any(marker in segment for marker in markers):
            continue
        if token not in ungated:
            ungated.append(token)
    if not ungated:
        return
    raise UngatedFarmSubmissionError(command, ungated, markers)


# --- client ----------------------------------------------------------------


class PueueClient:
    """Thin, real wrapper around the `pueue`/`pueued` CLI. Every method
    below shells out via an injected ProcRunner (default: real
    subprocess.run with a SANITIZED environment -- see module docstring) so
    tests can exercise this class's own argv-building/JSON-parsing logic
    without a live pueue daemon, while a smaller set of real integration
    tests also drive the actual installed pueue.exe (it is local, offline,
    and under this project's own control, unlike the license
    server/scheduler preflight.py talks to -- a real local daemon call in a
    test is legitimate here)."""

    def __init__(self, cfg: Optional[PueueConfig] = None,
                 runner: Optional[ProcRunner] = None,
                 daemon_starter: Optional[DaemonStarter] = None):
        self.cfg = cfg or PueueConfig()
        self._runner = runner or _default_proc_runner
        self._daemon_starter = daemon_starter or _default_daemon_starter
        self._binary = _resolve_binary(self.cfg.binary, self.cfg.extra_bin_dirs)
        self._daemon_binary = _resolve_binary(self.cfg.daemon_binary, self.cfg.extra_bin_dirs)

    def _env(self) -> Dict[str, str]:
        return _sanitize_env()

    def _call(self, args: List[str], timeout: int = 30) -> ProcResult:
        return self._runner([self._binary, *args], self._env(), timeout)

    def version(self) -> str:
        res = self._call(["--version"], timeout=10)
        if not res.ok:
            raise PueueError(f"pueue --version failed: {res.error or res.stderr}")
        return res.stdout.strip()

    def is_daemon_running(self) -> bool:
        res = self._call(["status", "-j"], timeout=10)
        return res.ok

    def ensure_daemon(self, timeout: int = 15) -> bool:
        """Starts pueued (--daemonize) if `pueue status` cannot reach a
        daemon yet, THEN ensures this client's own configured group
        (default "dv_harness") exists -- a real, confirmed finding
        (2026-09-03): pueue only ships a "default" group out of the box;
        `pueue add -g <group>` against a not-yet-created group fails
        outright ("Group <name> doesn't exists"), it does not
        auto-create one. Returns True once a daemon answers AND the
        group is confirmed present, False if the daemon never comes up
        within `timeout` seconds. Never assumes success -- polls real
        `pueue status` after starting rather than declaring victory the
        moment Popen() returns."""
        daemon_up = self.is_daemon_running()
        if not daemon_up:
            self._daemon_starter([self._daemon_binary, "--daemonize"], self._env())
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if self.is_daemon_running():
                    daemon_up = True
                    break
                time.sleep(0.5)
        if not daemon_up:
            return False
        try:
            groups = self.status().get("groups", {})
        except PueueError:
            return False
        if self.cfg.group not in groups:
            self.group_add(self.cfg.group)
        return True

    def group_add(self, name: str) -> ProcResult:
        return self._call(["group", "add", name], timeout=10)

    def add(self, command: str, *, label: Optional[str] = None,
            after: Optional[Sequence[int]] = None, group: Optional[str] = None,
            working_directory: Optional[str] = None, immediate: bool = False,
            timeout: int = 30, allow_ungated_farm_submit: bool = False) -> int:
        """Enqueues ONE task. Returns the real pueue task id (via
        `-p/--print-task-id`, so the id is parsed from bare stdout, never
        guessed from ordering). Raises PueueError on any failure -- a
        caller must never treat a missing/unparseable id as "probably
        task 0".

        Refuses, BEFORE `pueue add` is invoked at all, a command that would
        run a raw `bsub`/`sbatch` around the preflight gate
        (UngatedFarmSubmissionError -- see
        assert_farm_submission_is_preflight_gated()).
        `allow_ungated_farm_submit=True` is the single named, greppable
        override, mirroring `lsf_client.bsub_submit_with_preflight()`'s own
        explicit `skip_preflight` opt-out rather than inventing a second
        style of exemption. It exists for the guard's known false-positive
        shape -- a task that merely MENTIONS the token past a wrapper, e.g.
        `ssh host "grep bsub sim.log"` -- and never as a way to submit a real
        job un-gated. It is deliberately NOT exposed as a `dv-harness pueue
        add` flag, so the CLI path has no bypass at all."""
        if not allow_ungated_farm_submit:
            assert_farm_submission_is_preflight_gated(command)
        args = ["add", "-p"]
        if label:
            args += ["-l", label]
        for dep in (after or []):
            args += ["-a", str(int(dep))]
        args += ["-g", group or self.cfg.group]
        if working_directory:
            args += ["-w", working_directory]
        if immediate:
            args.append("-i")
        args += ["--", command]
        res = self._call(args, timeout=timeout)
        if not res.ok:
            raise PueueError(f"pueue add failed: {res.error or res.stderr or res.stdout}")
        text = res.stdout.strip()
        try:
            return int(text)
        except ValueError:
            raise PueueError(f"pueue add did not return a task id: {text!r}")

    def status(self, group: Optional[str] = None, timeout: int = 15) -> dict:
        args = ["status", "-j"]
        if group:
            args += ["-g", group]
        res = self._call(args, timeout=timeout)
        if not res.ok:
            raise PueueError(f"pueue status failed: {res.error or res.stderr}")
        try:
            return json.loads(res.stdout)
        except json.JSONDecodeError as e:
            raise PueueError(f"pueue status returned unparseable JSON: {e}") from e

    def log(self, task_ids: Optional[Sequence[int]] = None, full: bool = False,
            timeout: int = 15) -> dict:
        args = ["log", "-j"]
        if full:
            args.append("-f")
        args += [str(int(t)) for t in (task_ids or [])]
        res = self._call(args, timeout=timeout)
        if not res.ok:
            raise PueueError(f"pueue log failed: {res.error or res.stderr}")
        try:
            return json.loads(res.stdout)
        except json.JSONDecodeError as e:
            raise PueueError(f"pueue log returned unparseable JSON: {e}") from e

    def clean(self, group: Optional[str] = None, timeout: int = 15) -> ProcResult:
        """Removes finished tasks (and, load-bearingly, the plaintext
        captured-env snapshot pueue's daemon was holding for them -- see
        module docstring). Call this once a chain is done rather than
        leaving finished tasks (and their sanitized-but-still-real envs)
        sitting in state.json indefinitely."""
        args = ["clean"]
        if group:
            args += ["-g", group]
        return self._call(args, timeout=timeout)

    @staticmethod
    def _status_key_and_result(task: dict):
        """A pueue task's `status` field is always a single-key dict whose
        key names the state (`{"Running": {...}}`, `{"Done": {...}}`, ...)
        -- confirmed live against real pueue 4.0.4 output, 2026-09-03 (see
        .work/governance-pueue-notify-report.md for the captured
        transcript covering Queued/Running/Done-Success/Done-Failed).
        Returns (state_name, result) where `result` is only meaningful
        (and only present) once state_name == "Done": either the string
        "Success" or a {"Failed": exit_code} / other non-success variant."""
        status = task.get("status")
        if not isinstance(status, dict) or not status:
            return (str(status), None)
        state_name, body = next(iter(status.items()))
        result = body.get("result") if isinstance(body, dict) else None
        return (state_name, result)

    def wait(self, task_id: int, poll_interval: float = 2.0, timeout: int = 1800) -> dict:
        """Polls real `pueue status` until `task_id` reaches Done (or
        `timeout` seconds elapse). Returns {"task_id", "state", "result",
        "success"} -- `success` is True only for state=="Done" AND
        result=="Success"; a dependency-chain failure, a nonzero exit, a
        kill, or a timeout all come back success=False, never silently
        treated as fine."""
        deadline = time.monotonic() + timeout
        while True:
            snap = self.status()
            task = snap.get("tasks", {}).get(str(task_id))
            if task is None:
                raise PueueError(f"task {task_id} not found in pueue status")
            state_name, result = self._status_key_and_result(task)
            if state_name == "Done":
                return {"task_id": task_id, "state": state_name, "result": result,
                        "success": result == "Success"}
            if time.monotonic() >= deadline:
                return {"task_id": task_id, "state": state_name, "result": None,
                        "success": False, "timed_out": True}
            time.sleep(poll_interval)


# --- real harness chain helper --------------------------------------------


def enqueue_harness_chain(client: PueueClient, steps: Sequence[Sequence[str]],
                           group: Optional[str] = None) -> "List[Dict[str, object]]":
    """Enqueues `steps` (each a (label, command) pair) as a real pueue
    dependency chain: step N only starts once step N-1 has SUCCEEDED
    (pueue's own `-a/--after` semantics: "As soon as one of the
    dependencies fails, this task will fail as well" -- confirmed in
    `pueue add --help`). Returns [{"label", "task_id"}, ...] in the same
    order as `steps`.

    Every `command` string is exactly what the caller supplied -- this
    function never rewrites or synthesizes a bsub/sbatch/remote_exec.py
    invocation. A caller building the real DV pipeline passes e.g.
    `python tools/remote/remote_exec.py "make compile"` for a build step, or
    `dv-harness lsf-submit ...` (which itself runs the real, preflight-GATED
    bsub) for a submit step -- pueue's own role ends the moment that ONE
    shell command exits; it never tracks the resulting farm job's own
    lifecycle (that stays dv_harness.regression_reporter's lsf-watch-start
    watcher, per this module's own docstring).

    Every command IS checked against the un-gated farm-submission guard, and
    ALL of them are checked BEFORE the first `pueue add` -- one step running a
    raw `bsub`/`sbatch` raises UngatedFarmSubmissionError with the chain
    entirely un-enqueued, rather than leaving a half-built dependency chain
    behind whose earlier tasks are already running."""
    for _, command in steps:
        assert_farm_submission_is_preflight_gated(command)
    enqueued: List[Dict[str, object]] = []
    prev_id: Optional[int] = None
    for label, command in steps:
        after = [prev_id] if prev_id is not None else None
        task_id = client.add(command, label=label, after=after, group=group)
        enqueued.append({"label": label, "task_id": task_id})
        prev_id = task_id
    return enqueued
