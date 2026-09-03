"""dv_harness/connectivity_check.py -- the STANDING connectivity-check
runner (2026-09-04, bind-location/3-machine-gates gap closure).

WHY THIS EXISTS
---------------
`dv_harness/connectivity.py` already contains the real 3-gate standard
(Gate 1 elaboration / Gate 2 static zero-time connectivity / Gate 3
transaction activity) and the real aggregate entry point
`run_machine_gates()`. What it did NOT have, confirmed by direct search on
2026-09-04, was any way for those gates to be re-run automatically when the
RTL changes:

  - the root `justfile` had recipes for build/verify/run/regress/check/
    fsdbreport, but none that invoked any gate;
  - `.github/workflows/dv-harness-ci.yml` ran only pytest + self_audit;
  - `dv_harness/cli.py` had zero references to connectivity/gate3;
  - `connectivity.py` was imported by nothing but itself and
    `uvm_generator/bind_verification_lint.py`.

So Gate 3 was a manually-invocable function whose own docstring
(`run_gate3_against_live_simv()`: "recommended as a standing 'just
connectivity-check' recipe re-run on every RTL update") described a recipe
that did not exist. This module IS that recipe's implementation, and
`just connectivity-check` / the CI step / `python -m
dv_harness.connectivity_check` are its invocation points.

WHAT "RE-RUN ON EVERY RTL UPDATE" MEANS MECHANICALLY
----------------------------------------------------
A recipe someone has to remember to type is not a standing gate. The
standing part is the RTL FINGERPRINT: every real run records a content hash
of the project's declared RTL sources alongside the gate statuses it
produced. `--check-only` then re-computes that fingerprint and compares --
if the RTL moved since the last recorded gate run, the recorded gate
verdicts describe *different RTL* and are therefore STALE, which exits
nonzero. Wired into CI (and installable as a pre-push hook), that turns
"RTL changed but nobody re-ran connectivity" into a real, automatic
failure rather than something a reviewer has to notice.

This deliberately extends the existing real code rather than creating a
parallel mechanism: gate execution is `connectivity.run_machine_gates()`,
statuses are `connectivity.GateStatus`, the emitted report section is
`connectivity.render_bind_verification_status_markdown()` (so the artifact
this writes is exactly what `uvm_generator/bind_verification_lint.py`
already knows how to lint), and the JSON block is
`connectivity.bind_verification_status_block()`.

HONEST LIMITS
-------------
- Gate 1 still reports NOT_AVAILABLE where neither `slang` nor `vcs` is on
  PATH; Gate 2/3 still report NOT_AVAILABLE where no real trace / monitor
  transaction counts are supplied. This runner never fabricates evidence to
  turn one of those into a PASS -- it records the honest status and, per
  `GateReport.ready_for_human_review()`, only a real FAIL is a nonzero
  gate-run exit.
- A project with no `.dv-harness/connectivity_check.json` is NOT_CONFIGURED.
  `--check-only` exits 0 there (this harness repo itself has no RTL tree, so
  its own CI step is honestly a no-op until a project configures one) while
  a real gate run exits EXIT_CONFIG_ERROR, because running gates without a
  config is not something that can be silently approximated.
- A config whose `rtl_sources` match zero files is a real misconfiguration,
  not an empty project: it exits EXIT_CONFIG_ERROR in both modes, so a typo
  in a glob can never produce a vacuous constant fingerprint that compares
  equal forever and makes the staleness check permanently green.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from dv_harness import connectivity
from dv_harness.connectivity import (
    GateReport,
    GateStatus,
    SignalTrace,
    bind_verification_status_block,
    render_bind_verification_status_markdown,
)

#: Default config/state/report locations, all under the project's existing
#: `.dv-harness/` state directory (the same directory `state.json`,
#: `events.jsonl` and the rest of this harness's real run state already live
#: in -- not a new parallel state root).
DEFAULT_CONFIG_RELPATH = ".dv-harness/connectivity_check.json"
DEFAULT_STATE_RELPATH = ".dv-harness/connectivity_check_state.json"
DEFAULT_REPORT_RELPATH = ".dv-harness/connectivity_check_report.md"

#: Blackboard topic a real gate run publishes its 3 statuses into (2026-09-04).
#: The state file and the markdown report above are both artifacts a HUMAN
#: opens; neither is reachable from a graph stage, whose only structured view
#: of current truth is its node's `blackboard_read` snapshot (engine.py's
#: `_gather_stage_context`). Before this topic existed, a BUILD_DEBUG or
#: SIGNOFF stage had no way to see that Gate 2 had FAILED -- CLAUDE.md's
#: "Blackboard stores current verification truth" rule was simply not met for
#: the 3-gate standard. Written only on a real `write=True` run, so a
#: `--check-only` staleness probe (which runs no gate) can never refresh the
#: topic and make stale verdicts look current.
BLACKBOARD_TOPIC = "connectivity_gates"

EXIT_OK = 0
EXIT_GATE_FAIL = 1
EXIT_STALE = 2
EXIT_CONFIG_ERROR = 3


class ConnectivityCheckConfigError(connectivity.ConnectivityError):
    """Raised for a missing/unreadable/vacuous connectivity-check config.
    Subclasses this module's existing `ConnectivityError` (same convention
    as `ConnectivitySelfCheckError`/`BindTierError`/`BindGateCheckpointError`)
    rather than introducing an unrelated exception hierarchy."""


# ---- RTL fingerprint --------------------------------------------------------

def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def collect_rtl_files(project_root, rtl_sources: list) -> list:
    """Every real file matched by the config's `rtl_sources` globs, as
    project-root-relative POSIX paths, deduplicated and sorted. Sorting is
    what makes the resulting fingerprint independent of filesystem
    enumeration order (glob order differs between platforms), so the same
    tree fingerprints identically on Windows and Linux."""
    root = Path(project_root)
    found = set()
    for pattern in rtl_sources:
        for p in root.glob(pattern):
            if p.is_file():
                found.add(p.relative_to(root).as_posix())
    return sorted(found)


def compute_rtl_fingerprint(project_root, rtl_sources: list) -> dict:
    """Content fingerprint of the declared RTL set. Hashes file CONTENT, not
    mtime -- an mtime-based trigger fires on a no-op touch/checkout and
    misses a content change that preserves mtime, neither of which is the
    question this gate asks ("is the RTL these gate verdicts were produced
    against still the RTL on disk?")."""
    files = collect_rtl_files(project_root, rtl_sources)
    root = Path(project_root)
    h = hashlib.sha256()
    per_file = {}
    for rel in files:
        digest = _hash_file(root / rel)
        per_file[rel] = digest
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(digest.encode("ascii"))
        h.update(b"\n")
    return {"fingerprint": h.hexdigest(), "file_count": len(files), "files": per_file}


# ---- Config / state ---------------------------------------------------------

@dataclass
class ConnectivityCheckConfig:
    """The declared inputs a project supplies once, so the standing recipe
    needs no per-invocation arguments. Every field maps 1:1 onto a real
    parameter of `connectivity.run_machine_gates()` -- this dataclass adds
    no gate semantics of its own, it only makes those parameters
    file-declarable."""
    rtl_sources: list
    filelists: list = field(default_factory=list)
    top_module: str = ""
    signal_trace_path: Optional[str] = None
    clock_signal: str = "clk"
    reset_signal: str = "rst_n"
    reset_active_low: bool = True
    required_nonx_signals: list = field(default_factory=list)
    monitor_transaction_counts_path: Optional[str] = None
    monitor_transaction_counts: Optional[dict] = None
    pattern_completed: Optional[bool] = None


def load_config(path) -> ConnectivityCheckConfig:
    p = Path(path)
    if not p.is_file():
        raise ConnectivityCheckConfigError(
            "CONNECTIVITY_CHECK_NOT_CONFIGURED",
            {"expected_config": str(p)},
        )
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConnectivityCheckConfigError(
            "CONNECTIVITY_CHECK_CONFIG_UNPARSEABLE", {"path": str(p), "error": str(exc)}
        ) from exc
    if not isinstance(data, dict):
        raise ConnectivityCheckConfigError(
            "CONNECTIVITY_CHECK_CONFIG_NOT_AN_OBJECT", {"path": str(p)}
        )
    rtl_sources = data.get("rtl_sources") or []
    if not isinstance(rtl_sources, list) or not rtl_sources:
        raise ConnectivityCheckConfigError(
            "CONNECTIVITY_CHECK_CONFIG_HAS_NO_RTL_SOURCES",
            {"path": str(p),
             "why": ("rtl_sources is what the staleness trigger fingerprints; with none "
                     "declared there is no 're-run on every RTL update' behavior at all.")},
        )
    return ConnectivityCheckConfig(
        rtl_sources=list(rtl_sources),
        filelists=list(data.get("filelists") or []),
        top_module=data.get("top_module") or "",
        signal_trace_path=data.get("signal_trace_path"),
        clock_signal=data.get("clock_signal", "clk"),
        reset_signal=data.get("reset_signal", "rst_n"),
        reset_active_low=bool(data.get("reset_active_low", True)),
        required_nonx_signals=list(data.get("required_nonx_signals") or []),
        monitor_transaction_counts_path=data.get("monitor_transaction_counts_path"),
        monitor_transaction_counts=data.get("monitor_transaction_counts"),
        pattern_completed=data.get("pattern_completed"),
    )


def load_state(path) -> Optional[dict]:
    """The last recorded real gate run, or None when this project has never
    run one. None is deliberately NOT treated as 'up to date' by
    `evaluate_staleness()` -- never having run the gates at all is exactly
    the situation the checkpoint exists to catch."""
    p = Path(path)
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def evaluate_staleness(state: Optional[dict], current_fingerprint: str) -> dict:
    """The standing trigger. Returns `{stale, reason, ...}`; `stale=True`
    means the recorded gate verdicts do not describe the RTL currently on
    disk (or no gate run was ever recorded), so the gates must be re-run
    before any of their statuses may be cited."""
    if state is None:
        return {"stale": True, "reason": "NEVER_RUN",
                "detail": "no connectivity-check state recorded for this project yet"}
    recorded = state.get("rtl_fingerprint")
    if not recorded:
        return {"stale": True, "reason": "STATE_MISSING_FINGERPRINT",
                "detail": "recorded state carries no rtl_fingerprint to compare against"}
    if recorded != current_fingerprint:
        return {"stale": True, "reason": "RTL_CHANGED",
                "detail": f"recorded {recorded[:12]}... != current {current_fingerprint[:12]}...",
                "recorded_fingerprint": recorded, "current_fingerprint": current_fingerprint}
    return {"stale": False, "reason": "UP_TO_DATE", "detail": "RTL unchanged since the last gate run",
            "recorded_fingerprint": recorded, "current_fingerprint": current_fingerprint}


# ---- Gate execution ---------------------------------------------------------

def _load_signal_trace(project_root, rel: Optional[str]) -> Optional[SignalTrace]:
    """A trace file is `{"samples": {"<signal>": [[time, "value"], ...]}}` --
    exactly `SignalTrace`'s documented data contract, with the (time, value)
    pairs written as JSON arrays. Returns None when no trace is declared, so
    `run_machine_gates()` falls through to its honest
    `run_gate2_against_live_simv()` NOT_AVAILABLE result."""
    if not rel:
        return None
    p = Path(project_root) / rel
    if not p.is_file():
        return None
    data = json.loads(p.read_text(encoding="utf-8"))
    samples = data.get("samples", data) if isinstance(data, dict) else {}
    return SignalTrace(samples={
        sig: [(int(t), str(v)) for t, v in pairs] for sig, pairs in samples.items()
    })


def _load_monitor_counts(project_root, cfg: ConnectivityCheckConfig) -> Optional[dict]:
    if cfg.monitor_transaction_counts is not None:
        return dict(cfg.monitor_transaction_counts)
    if not cfg.monitor_transaction_counts_path:
        return None
    p = Path(project_root) / cfg.monitor_transaction_counts_path
    if not p.is_file():
        return None
    data = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "monitor_transaction_counts" in data:
        data = data["monitor_transaction_counts"]
    return {str(k): int(v) for k, v in data.items()} if isinstance(data, dict) else None


@dataclass
class ConnectivityCheckResult:
    rtl_fingerprint: str
    rtl_file_count: int
    staleness: dict
    gate_report: Optional[GateReport]
    status_block: dict
    exit_code: int


def run_connectivity_check(
    project_root,
    cfg: ConnectivityCheckConfig,
    *,
    state_path=None,
    report_path=None,
    which_fn: Optional[Callable[[str], Optional[str]]] = None,
    run_fn: Optional[Callable[..., Any]] = None,
    write: bool = True,
) -> ConnectivityCheckResult:
    """Runs all 3 gates for real via `connectivity.run_machine_gates()` (the
    single mandatory pipeline entry point -- this runner deliberately does
    not call the individual gates, so it can never run only 1 or 2 of them),
    then records the resulting statuses together with the RTL fingerprint
    they were produced against.

    `which_fn`/`run_fn` are passed straight through to Gate 1 so the same
    dependency-injection pattern `connectivity.py` established for its own
    tests works end-to-end here too, with no fake tool ever reaching a real
    invocation."""
    root = Path(project_root)
    fp = compute_rtl_fingerprint(root, cfg.rtl_sources)
    if fp["file_count"] == 0:
        raise ConnectivityCheckConfigError(
            "CONNECTIVITY_CHECK_RTL_SOURCES_MATCHED_NOTHING",
            {"rtl_sources": cfg.rtl_sources, "project_root": str(root),
             "why": ("an empty RTL set fingerprints to a constant, which would compare equal "
                     "forever and make the staleness trigger permanently green.")},
        )
    state_path = Path(state_path) if state_path else root / DEFAULT_STATE_RELPATH
    report_path = Path(report_path) if report_path else root / DEFAULT_REPORT_RELPATH

    prior = load_state(state_path)
    staleness = evaluate_staleness(prior, fp["fingerprint"])

    kwargs: dict = {}
    if which_fn is not None:
        kwargs["which_fn"] = which_fn
    if run_fn is not None:
        kwargs["run_fn"] = run_fn
    report = connectivity.run_machine_gates(
        filelist_paths=[str(root / f) for f in cfg.filelists],
        top_module=cfg.top_module,
        signal_trace=_load_signal_trace(root, cfg.signal_trace_path),
        clock_signal=cfg.clock_signal,
        reset_signal=cfg.reset_signal,
        required_nonx_signals=cfg.required_nonx_signals,
        monitor_transaction_counts=_load_monitor_counts(root, cfg),
        pattern_completed=cfg.pattern_completed,
        **kwargs,
    )
    block = bind_verification_status_block(report)
    exit_code = EXIT_GATE_FAIL if not report.ready_for_human_review() else EXIT_OK

    if write:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps({
            "recorded_at": connectivity._utcnow_iso(),
            "rtl_fingerprint": fp["fingerprint"],
            "rtl_file_count": fp["file_count"],
            "rtl_files": fp["files"],
            "bind_verification_status": block,
            "gate_detail": {
                g.gate: {"status": g.status.value, "detail": g.detail}
                for g in (report.gate1, report.gate2, report.gate3)
            },
            "staleness_at_run": staleness,
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(render_connectivity_check_report(fp, staleness, report) + "\n",
                               encoding="utf-8")
        sync_gates_to_blackboard(root, fp, staleness, report, block)

    return ConnectivityCheckResult(
        rtl_fingerprint=fp["fingerprint"], rtl_file_count=fp["file_count"],
        staleness=staleness, gate_report=report, status_block=block, exit_code=exit_code,
    )


def sync_gates_to_blackboard(project_root, fingerprint: dict, staleness: dict,
                               report: Optional[GateReport], block: dict,
                               *, blackboard=None) -> Optional[dict]:
    """Publish this real gate run's 3 statuses into the `connectivity_gates`
    Blackboard topic and return the written entry.

    The value carries each gate's own `GateStatus` VALUE verbatim -- PASS /
    FAIL / NOT_AVAILABLE / PENDING / NOT_YET_RUN stay five distinct states,
    never collapsed into a boolean. That distinction is the whole point of
    the enum (CLAUDE.md: NOT_AVAILABLE and PENDING must "never be conflated
    with FAILED"), and a stage reading this topic has to be able to tell "no
    slang/vcs on PATH" from "the bind is wrong".

    The RTL fingerprint the gates ran against travels with them, so a reader
    can tell whether the verdicts still describe the current RTL rather than
    having to trust that the topic was refreshed.

    Best-effort by design: a blackboard write failure must never turn an
    already-completed gate run (whose state file and report are on disk) into
    a failed run."""
    try:
        if blackboard is None:
            from dv_harness.blackboard import Blackboard
            blackboard = Blackboard(Path(project_root))
        gates = {}
        for gate in ((report.gate1, report.gate2, report.gate3) if report is not None else ()):
            gates[gate.gate] = {"status": gate.status.value, "detail": gate.detail}
        value = {
            "rtl_fingerprint": fingerprint.get("fingerprint"),
            "rtl_file_count": fingerprint.get("file_count"),
            "staleness_at_run": staleness,
            "bind_verification_status": block,
            "gates": gates,
            "ready_for_human_review": report.ready_for_human_review() if report is not None else None,
            "not_available_gates": report.not_available_gates() if report is not None else [],
            "pending_gates": report.pending_gates() if report is not None else [],
        }
        return blackboard.write(BLACKBOARD_TOPIC, value, source="connectivity-check")
    except Exception as e:
        print(f"[connectivity-check] blackboard gate-status sync failed: {e}", flush=True)
        return None


def render_connectivity_check_report(fingerprint: dict, staleness: dict,
                                     report: Optional[GateReport]) -> str:
    """Emits `render_bind_verification_status_markdown()` verbatim as its
    core section, so the artifact this runner writes is lint-clean under the
    existing `python -m dv_harness.uvm_generator.bind_verification_lint`
    without that lint needing to learn a second report format."""
    lines = [
        "# Connectivity Check (standing 3-gate recipe)",
        "",
        f"- RTL fingerprint: `{fingerprint['fingerprint']}`",
        f"- RTL files fingerprinted: {fingerprint['file_count']}",
        f"- Staleness at run: {staleness['reason']} -- {staleness['detail']}",
        "",
        render_bind_verification_status_markdown(report),
        "",
    ]
    if report is not None:
        na = report.not_available_gates()
        pending = report.pending_gates()
        if na:
            lines.append(f"- NOT_AVAILABLE gates (real tooling/data gaps, never read as PASS): {', '.join(na)}")
        if pending:
            lines.append(f"- PENDING gates (workflow prerequisite not reached yet, never read as FAIL): {', '.join(pending)}")
    return "\n".join(lines)


# ---- CLI --------------------------------------------------------------------

def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m dv_harness.connectivity_check",
        description=(
            "Standing connectivity check: re-runs connectivity.py's 3 machine gates "
            "(elaboration / static zero-time connectivity / transaction activity) and "
            "records the RTL fingerprint they were produced against, so a later "
            "--check-only run can fail when the RTL moved but the gates were not re-run."
        ),
    )
    parser.add_argument("--project-root", default=".", help="Project root (default: cwd)")
    parser.add_argument("--config", default=None,
                        help=f"Config JSON (default: <project-root>/{DEFAULT_CONFIG_RELPATH})")
    parser.add_argument("--state", default=None,
                        help=f"State JSON (default: <project-root>/{DEFAULT_STATE_RELPATH})")
    parser.add_argument("--report", default=None,
                        help=f"Markdown report to write (default: <project-root>/{DEFAULT_REPORT_RELPATH})")
    parser.add_argument("--check-only", action="store_true",
                        help=("Do not run the gates; only compare the current RTL fingerprint "
                              "against the last recorded gate run. Exits 2 when the RTL changed "
                              "(or no run was ever recorded) -- this is the CI/hook trigger."))
    args = parser.parse_args(argv)

    root = Path(args.project_root).resolve()
    config_path = Path(args.config) if args.config else root / DEFAULT_CONFIG_RELPATH
    state_path = Path(args.state) if args.state else root / DEFAULT_STATE_RELPATH

    try:
        cfg = load_config(config_path)
    except ConnectivityCheckConfigError as exc:
        if exc.reason == "CONNECTIVITY_CHECK_NOT_CONFIGURED" and args.check_only:
            # Honest no-op: a project (this harness repo included) with no RTL
            # tree has nothing for the standing trigger to watch. Reported
            # explicitly rather than printed as a pass.
            print(f"CONNECTIVITY-CHECK: NOT_CONFIGURED -- no {config_path} in this project; "
                  f"nothing to fingerprint. (Create it to enable the standing RTL-change trigger.)")
            return EXIT_OK
        print(f"CONNECTIVITY-CHECK: CONFIG ERROR {exc.reason} -- {exc.detail}")
        return EXIT_CONFIG_ERROR

    if args.check_only:
        try:
            fp = compute_rtl_fingerprint(root, cfg.rtl_sources)
        except OSError as exc:
            print(f"CONNECTIVITY-CHECK: CONFIG ERROR unreadable RTL source -- {exc}")
            return EXIT_CONFIG_ERROR
        if fp["file_count"] == 0:
            print("CONNECTIVITY-CHECK: CONFIG ERROR CONNECTIVITY_CHECK_RTL_SOURCES_MATCHED_NOTHING -- "
                  f"rtl_sources {cfg.rtl_sources} matched no files under {root}")
            return EXIT_CONFIG_ERROR
        staleness = evaluate_staleness(load_state(state_path), fp["fingerprint"])
        if staleness["stale"]:
            print(f"CONNECTIVITY-CHECK: STALE ({staleness['reason']}) -- {staleness['detail']}")
            print("  The 3 machine gates must be re-run against the current RTL before their "
                  "statuses may be cited. Run: just connectivity-check")
            return EXIT_STALE
        state = load_state(state_path) or {}
        block = state.get("bind_verification_status", {})
        print(f"CONNECTIVITY-CHECK: UP_TO_DATE -- {fp['file_count']} RTL file(s), "
              f"fingerprint {fp['fingerprint'][:12]}...")
        for key, value in block.items():
            print(f"  {key}: {value}")
        return EXIT_OK

    try:
        result = run_connectivity_check(
            root, cfg, state_path=state_path,
            report_path=Path(args.report) if args.report else None,
        )
    except ConnectivityCheckConfigError as exc:
        print(f"CONNECTIVITY-CHECK: CONFIG ERROR {exc.reason} -- {exc.detail}")
        return EXIT_CONFIG_ERROR

    print(f"CONNECTIVITY-CHECK: ran 3 machine gates over {result.rtl_file_count} RTL file(s), "
          f"fingerprint {result.rtl_fingerprint[:12]}... "
          f"(was {result.staleness['reason']})")
    for key, value in result.status_block.items():
        print(f"  {key}: {value}")
    if result.exit_code == EXIT_GATE_FAIL:
        failing = [g.gate for g in (result.gate_report.gate1, result.gate_report.gate2,
                                    result.gate_report.gate3) if g.status == GateStatus.FAIL]
        print(f"  FAIL: {', '.join(failing)} -- a connectivity plan with a FAILing gate is not "
              "ready for human review (GateReport.ready_for_human_review()).")
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
