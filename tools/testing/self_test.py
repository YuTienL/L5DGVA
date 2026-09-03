#!/usr/bin/env python3
"""Harness self-test: CI for the HARNESS'S OWN scripts, not for a DUT/UVM
environment the harness generates. Per the user's own framing (2026-09-03
harness-self-test-ci workstream): "agent 的基礎設施壞掉比 agent 判斷錯更難察覺"
-- the harness's own infrastructure breaking is a harder-to-notice failure
mode than the agent making a wrong judgment call, so it needs its own cheap,
fast, always-runnable regression net independent of any GitHub Actions
runner.

Four checks, run in this order (cheapest/most-diagnostic first, so a broken
import is reported before wasting time on a full pytest run that would fail
for the same root cause anyway):

  1. import-sanity  -- every real, importable module under dv_harness/ is
     imported via importlib and must not raise. Catches a broken import
     before any real CLI invocation, test collection, or generated
     environment would hit it first. Deliberately excludes:
       - dv_harness/__main__.py: plain top-level `main()` call (no
         `if __name__ == "__main__"` guard) -- importing it *runs* the CLI
         with no argv, which is not what an import-sanity check means. Its
         own syntax/importability is still covered indirectly by `main`
         being importable from dv_harness.cli, which this check does cover.
       - dv_harness/uvm_generator/templates/**/*.py: these are template
         ASSETS copied verbatim into a generated UVM environment's own
         sim/check tree (gen_pattern_pool.py, the check/*.py static
         checkers, ...) -- not package modules of dv_harness itself (no
         __init__.py anywhere under templates/), so they are not on any
         dotted import path. This mirrors the exact reasoning
         pyproject.toml's own `[tool.pytest.ini_options]` comment already
         gives for excluding tools/verification_flow/test_*.py from pytest
         collection: standalone argparse scripts that only happen to share
         a filename pattern with real package modules.

  2. cli-help-sanity -- every subcommand argparse registers under
     `dv-harness` (discovered live from the real parser's own `--help`
     output, not a hand-maintained list that would silently drift out of
     sync with dv_harness/cli.py) is invoked with `--help` and must exit 0
     with no traceback. A cheap regression net against the "harness's own
     CLI is broken" failure mode: an argparse wiring mistake, a bad default,
     a typo'd flag name, or an import that only blows up inside one
     subcommand's lazy `from . import X` (cli.py imports most submodules
     lazily per-subcommand, so import-sanity above importing dv_harness.cli
     itself does not exercise those lazy imports -- this check does).
     Recurses into nested subparsers (e.g. `blackboard write`/`read`,
     `memory status`/`search`/..., `pueue add`/`status`/...) to whatever
     depth the real parser actually has, discovered the same live way.

  3. self-audit -- the harness's own existing meta/registry-consistency
     gate suite (dv_harness/self_audit.py, `dv-harness self-audit`; see
     that module's docstring for the full 23-gate design). Reused as-is,
     not duplicated: this script imports and calls
     `self_audit.run_self_audit()` directly, the same "one implementation,
     N callers" pattern that module already documents for its CLI and
     dashboard callers -- this is simply a third caller. Fails this script
     iff self-audit reports a real FAIL (NO_SOURCE_DATA is not a failure --
     see self_audit.py's own Evidence Truth Rule discussion for why).

  4. pytest -- the real regression suite, `python -m pytest
     dv_harness_tests/ -q` (testpaths already scoped by pyproject.toml).
     Run last since it is by far the most expensive of the four (the suite
     includes real subprocess-driven integration tests -- e.g.
     test_cli_adapter_command_resolution.py's real `claude` CLI round trip,
     test_cli_pueue.py's real `pueued` daemon interaction -- not just pure
     unit tests, so wall time is minutes, not seconds; a generous default
     timeout is used for exactly this reason. See --pytest-timeout below to
     override for a slower/faster machine, and --skip-pytest to omit it
     entirely for a fast three-check smoke pass during iteration.

Exit code: 0 iff every requested check passed. Non-zero otherwise, with a
per-check PASS/FAIL summary printed at the end (never only the first
failure -- a broken import very often ALSO breaks CLI --help and pytest
collection for the same root cause, and seeing all three fail together vs.
only pytest failing is itself diagnostic).

Usage:
    python tools/testing/self_test.py                  # all four checks
    python tools/testing/self_test.py --skip-pytest     # fast 3-check pass
    python tools/testing/self_test.py --only import-sanity
    python tools/testing/self_test.py --pytest-timeout 1800
    python tools/testing/self_test.py --json            # machine-readable

Exists as a plain script (not a `dv-harness` subcommand) so it never
requires editing dv_harness/cli.py -- see .work/harness-self-test-ci-
report.md for why that choice was made this session.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
DV_HARNESS_DIR = REPO_ROOT / "dv_harness"
TESTS_DIR = REPO_ROOT / "dv_harness_tests"

# Running this file directly (`python tools/testing/self_test.py`) puts
# tools/testing/ on sys.path[0], NOT the repo root -- `import dv_harness`
# would otherwise fail with ModuleNotFoundError regardless of cwd. Insert
# the repo root explicitly rather than relying on the caller's cwd or an
# editable install being present.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_PYTEST_TIMEOUT = 1800  # seconds -- see module docstring's check 4.
DEFAULT_CLI_HELP_TIMEOUT = 30  # seconds per `--help` invocation.
DEFAULT_MAX_SUBCOMMAND_DEPTH = 4  # real parser today nests at most 2 deep
                                   # (e.g. `memory` -> `search`); headroom
                                   # kept generous rather than hard-coded to
                                   # today's exact depth.

CHECK_NAMES = ["import-sanity", "cli-help-sanity", "self-audit", "pytest"]


class CheckResult:
    __slots__ = ("name", "ok", "seconds", "detail")

    def __init__(self, name: str, ok: bool, seconds: float, detail: Dict[str, Any]):
        self.name, self.ok, self.seconds, self.detail = name, ok, seconds, detail

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "ok": self.ok, "seconds": round(self.seconds, 2), "detail": self.detail}


# --- 1. import-sanity --------------------------------------------------------

def _discover_importable_modules() -> List[str]:
    """Every real dv_harness/*.py file, as a dotted module name, excluding
    __main__.py (executes main() at import time -- see module docstring)
    and anything under uvm_generator/templates/ (template assets, not
    package modules -- no __init__.py exists anywhere under templates/, so
    these are not genuinely on any dotted import path)."""
    names = []
    for path in sorted(DV_HARNESS_DIR.rglob("*.py")):
        rel = path.relative_to(REPO_ROOT)
        parts = rel.parts
        if "__pycache__" in parts:
            continue
        if "templates" in parts:
            continue
        if rel.name == "__main__.py":
            continue
        if rel.name == "__init__.py":
            dotted = ".".join(parts[:-1])
        else:
            dotted = ".".join(parts).removesuffix(".py")
        names.append(dotted)
    return names


def run_import_sanity() -> CheckResult:
    t0 = time.monotonic()
    modules = _discover_importable_modules()
    failures = []
    for name in modules:
        # Fresh interpretation of each module's own top-level code every
        # time this check runs, not a cached prior success -- pop any
        # already-imported entry (and its submodules) first.
        for cached in [m for m in sys.modules if m == name or m.startswith(name + ".")]:
            sys.modules.pop(cached, None)
        try:
            importlib.import_module(name)
        except BaseException as exc:  # noqa: BLE001 -- a bad module can raise anything, incl. SystemExit
            failures.append({"module": name, "error": f"{type(exc).__name__}: {exc}",
                              "traceback": traceback.format_exc(limit=6)})
    ok = not failures
    return CheckResult("import-sanity", ok, time.monotonic() - t0,
                        {"modules_checked": len(modules), "failures": failures})


# --- 2. cli-help-sanity -------------------------------------------------------

_SUBPARSER_CHOICES_RE = re.compile(r"\{([a-zA-Z0-9_,-]+)\}\s+\.\.\.")


def _run_help(argv: List[str], timeout: int) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, "-m", "dv_harness.cli", "--project-root", str(REPO_ROOT), *argv, "--help"],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=timeout, env=env,
    )


def _discover_subcommand_tree(path: List[str], timeout: int, depth: int,
                               failures: List[Dict[str, Any]], leaves: List[List[str]]) -> None:
    """Recursively walks the REAL argparse tree, discovered live from each
    level's own `--help` output -- never a hand-maintained command list, so
    this can never silently drift stale as cli.py gains/renames
    subcommands (the exact class of drift a hand-written list would be
    prone to)."""
    try:
        proc = _run_help(path, timeout)
    except subprocess.TimeoutExpired:
        failures.append({"path": path, "error": "HELP_TIMEOUT"})
        return
    if proc.returncode != 0:
        failures.append({"path": path, "error": "NONZERO_EXIT", "returncode": proc.returncode,
                          "stderr": (proc.stderr or "")[-2000:]})
        return
    m = _SUBPARSER_CHOICES_RE.search(proc.stdout)
    if not m or depth >= DEFAULT_MAX_SUBCOMMAND_DEPTH:
        leaves.append(path)
        return
    children = m.group(1).split(",")
    for child in children:
        _discover_subcommand_tree(path + [child], timeout, depth + 1, failures, leaves)


def run_cli_help_sanity(timeout: int = DEFAULT_CLI_HELP_TIMEOUT) -> CheckResult:
    t0 = time.monotonic()
    failures: List[Dict[str, Any]] = []
    leaves: List[List[str]] = []
    # Top level: `dv-harness --help` itself must also work.
    try:
        top = _run_help([], timeout)
    except subprocess.TimeoutExpired:
        return CheckResult("cli-help-sanity", False, time.monotonic() - t0,
                            {"error": "top-level `dv-harness --help` timed out"})
    if top.returncode != 0:
        return CheckResult("cli-help-sanity", False, time.monotonic() - t0,
                            {"error": "top-level `dv-harness --help` exited nonzero",
                             "stderr": (top.stderr or "")[-2000:]})
    m = _SUBPARSER_CHOICES_RE.search(top.stdout)
    top_commands = m.group(1).split(",") if m else []
    for cmd in top_commands:
        _discover_subcommand_tree([cmd], timeout, 1, failures, leaves)
    ok = not failures
    return CheckResult("cli-help-sanity", ok, time.monotonic() - t0,
                        {"top_level_commands": len(top_commands), "leaf_help_invocations": len(leaves),
                         "failures": failures})


# --- 3. self-audit ------------------------------------------------------------

def run_self_audit_check() -> CheckResult:
    t0 = time.monotonic()
    try:
        from dv_harness import self_audit
    except BaseException as exc:  # noqa: BLE001
        return CheckResult("self-audit", False, time.monotonic() - t0,
                            {"error": f"could not import dv_harness.self_audit: {type(exc).__name__}: {exc}"})
    try:
        result = self_audit.run_self_audit(REPO_ROOT)
    except BaseException as exc:  # noqa: BLE001
        return CheckResult("self-audit", False, time.monotonic() - t0,
                            {"error": f"run_self_audit() raised: {type(exc).__name__}: {exc}"})
    summary = result["summary"]
    ok = summary["fail"] == 0 and summary["smoke_fail"] == 0
    failing_gates = [g["gate_id"] for g in result["gates"] if g["status"] in ("FAIL", "SCRIPT_SMOKE_FAIL")]
    return CheckResult("self-audit", ok, time.monotonic() - t0,
                        {"summary": summary, "failing_gates": failing_gates})


# --- 4. pytest -----------------------------------------------------------------

def run_pytest_suite(timeout: int, extra_args: Optional[List[str]] = None) -> CheckResult:
    t0 = time.monotonic()
    env = os.environ.copy()
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env["OAI_IS_JUPYTER_KERNEL"] = "0"
    args = [sys.executable, "-m", "pytest", "dv_harness_tests/", "-q", *(extra_args or [])]
    try:
        proc = subprocess.run(args, cwd=str(REPO_ROOT), capture_output=True, text=True,
                               timeout=timeout, env=env)
    except subprocess.TimeoutExpired as exc:
        partial = (exc.stdout or "")[-4000:] if isinstance(exc.stdout, str) else ""
        return CheckResult("pytest", False, time.monotonic() - t0,
                            {"error": f"pytest exceeded --pytest-timeout={timeout}s", "partial_output": partial})
    ok = proc.returncode == 0
    tail = (proc.stdout or "")[-4000:]
    return CheckResult("pytest", ok, time.monotonic() - t0,
                        {"returncode": proc.returncode, "output_tail": tail})


# --- driver --------------------------------------------------------------------

CHECK_FUNCS = {
    "import-sanity": lambda args: run_import_sanity(),
    "cli-help-sanity": lambda args: run_cli_help_sanity(args.cli_help_timeout),
    "self-audit": lambda args: run_self_audit_check(),
    "pytest": lambda args: run_pytest_suite(args.pytest_timeout, args.pytest_args),
}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="self_test.py",
        description="Harness self-test: import-sanity + CLI --help sanity + self-audit + pytest, "
                     "the four cheap/real checks that catch the harness's OWN infrastructure breaking.")
    ap.add_argument("--only", action="append", choices=CHECK_NAMES, default=None,
                     help="Run only this check; repeatable. Omit to run all four in order.")
    ap.add_argument("--skip-pytest", action="store_true",
                     help="Shorthand for running only the three fast checks (import-sanity, "
                          "cli-help-sanity, self-audit) -- seconds, not minutes; useful while iterating.")
    ap.add_argument("--pytest-timeout", type=int, default=DEFAULT_PYTEST_TIMEOUT,
                     help=f"Seconds before the pytest step is treated as FAIL (default {DEFAULT_PYTEST_TIMEOUT}). "
                          "The suite includes real subprocess-driven integration tests, so this is "
                          "generous by design -- see the module docstring's check 4.")
    ap.add_argument("--cli-help-timeout", type=int, default=DEFAULT_CLI_HELP_TIMEOUT,
                     help=f"Seconds per single `--help` invocation (default {DEFAULT_CLI_HELP_TIMEOUT}).")
    ap.add_argument("--pytest-args", nargs=argparse.REMAINDER, default=None,
                     help="Extra args forwarded verbatim to the pytest invocation, e.g. "
                          "--pytest-args -k test_foo or --pytest-args -x.")
    ap.add_argument("--json", action="store_true", help="Print a single JSON result object instead of "
                                                          "the human-readable report.")
    args = ap.parse_args(argv)

    if args.only:
        order = [c for c in CHECK_NAMES if c in args.only]
    elif args.skip_pytest:
        order = [c for c in CHECK_NAMES if c != "pytest"]
    else:
        order = list(CHECK_NAMES)

    results: List[CheckResult] = []
    for name in order:
        if not args.json:
            print(f"==> {name} ...", flush=True)
        result = CHECK_FUNCS[name](args)
        results.append(result)
        if not args.json:
            status = "PASS" if result.ok else "FAIL"
            print(f"    {status} ({result.seconds:.1f}s)", flush=True)
            if not result.ok:
                # Print enough of the detail to act on immediately, without
                # requiring --json for the common case.
                for key in ("error", "failures", "failing_gates"):
                    if key in result.detail and result.detail[key]:
                        val = result.detail[key]
                        if isinstance(val, list) and len(val) > 5:
                            val = val[:5] + [f"... ({len(result.detail[key]) - 5} more)"]
                        print(f"      {key}: {val}", flush=True)

    overall_ok = all(r.ok for r in results)
    if args.json:
        print(json.dumps({"ok": overall_ok, "checks": [r.to_dict() for r in results]}, ensure_ascii=False, indent=2))
    else:
        print()
        print("=== self-test summary ===")
        for r in results:
            print(f"  [{'PASS' if r.ok else 'FAIL'}] {r.name} ({r.seconds:.1f}s)")
        print(f"Overall: {'PASS' if overall_ok else 'FAIL'}")
    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
