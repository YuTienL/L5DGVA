"""dv_harness/exec_eng_dashboard.py -- Executive + Engineering Dashboard
(2026-09-06, TARGETED_HARDENING section 241, id `gui_exec_eng_dashboard`).

Combines two ALREADY-REAL rollups into one view -- nothing here re-derives a
verdict either of them already owns:

  - `system_closure_aggregator.aggregate_system_closure()` -- the real,
    strict-worst-wins twelve-dimension closure fold.
  - `platform_health.platform_health_report()` -- the real per-subsystem
    HEALTHY/DEGRADED/CRITICAL/UNKNOWN platform picture plus SLO error budgets.

REUSE OVER REINVENT -- checked before writing a line of this. A repo-wide
grep found no module combining these two specific rollups into one GUI
view: `harness_status.py` (built earlier in this same batch, "Global Status
Bar") reads BOTH modules too, but for a different, wider purpose (a
thirteen-dimension `HarnessStatusIR` spanning loop telemetry, question
queue, signoff, subsystem maturity, AMBA gates, escalation notify) and it
deliberately supplies only FOUR of the twelve closure dimensions
(functional_coverage, protocol_coverage, requirement_closure,
regression_status) -- disclosed as an honest partial feed in its own
source. It renders no HTML, has no notion of an "executive summary card" or
an "engineering detail" drill-down, and its own gathering functions are
private (`_gather_*`) -- not a stable API this module should couple to.
This module is therefore standalone and honestly scoped: it does its OWN
narrow, disclosed best-effort gathering of two of the twelve closure
dimensions (`functional_coverage` via `functional_coverage_signoff.py`,
`waiver_status` via `waiver_store.py` -- both cited by
`system_closure_aggregator.py`'s own docstring as real per-dimension
producers), and accepts the remaining ten as an optional caller-supplied
override so a future orchestrator with more evidence can extend the
picture without editing this file. The ten dimensions this module does not
auto-source are reported `NOT_SUPPLIED` -- system_closure_aggregator's own
honest token -- never guessed toward MET.

GUI CARD PATTERN, REUSED WITHOUT TOUCHING dashboard.py -- dashboard.py was
verified, at the moment this module was written, to be under active
concurrent edit in this same session (its own mtime was the most recent of
any file in `dv_harness/`, alongside `cli.py` and `gates.py`), so per this
task's own house rule ("prefer a standalone `python -m dv_harness.<module>`
front door ... matching several recent modules that already made that same
disclosed choice") this module does not import or edit `dashboard.py`.
`_CARD_CSS` below is a literal, disclosed copy of the `.card`/`.tiles`/
`.tile` container rules and the `PASS`/`FAIL`/`PARTIAL`/`UNKNOWN` hex color
palette from `dashboard.py`'s own `HTML` template `<style>` block (as of
this writing) -- so a page rendered here looks like one more card on that
same dashboard, without a functional import of a 3600+-line file whose own
module-level side effects (constructing a `DVHarness`, a `ControlPlane`,
etc.) make it unsuitable to import for a lightweight render/test anyway.

WORST-WINS, NEVER AVERAGED -- the composite "banner" state on the Executive
Summary card is computed by literally calling `platform_health.worst()`
(not a re-derived fold) over the two rollups' own real states, mapped onto
`platform_health`'s own four-value `HEALTH_STATES` vocabulary
(`HEALTHY`/`DEGRADED`/`CRITICAL`/`UNKNOWN`) rather than inventing a fifth
vocabulary for this module's own banner. `CLOSED -> HEALTHY`,
`NOT_CLOSED -> CRITICAL`, `INCOMPLETE_EVIDENCE -> UNKNOWN` (never CLOSED
read as HEALTHY when the *platform* is unmeasured, and never a real
platform CRITICAL diluted by a clean closure picture -- `worst()` already
guarantees this by construction).

This module DECIDES nothing beyond the rollup + render: no build, no gate,
no job, no LSF submission, no approval is minted, and there is deliberately
no stage gate -- an executive/engineering dashboard is an input to a
human's review, never a substitute for one. It writes nothing to
`.dv-harness/` on its own; the only file it may write is an explicit
`--out <path>.html` snapshot the caller asked for.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import platform_health
from . import system_closure_aggregator as sca

try:
    from . import functional_coverage_signoff as _fcs
except Exception:  # pragma: no cover - defensive: never let an import crash the module
    _fcs = None

try:
    from . import waiver_store as _waiver_store
except Exception:  # pragma: no cover - defensive
    _waiver_store = None


class ExecEngDashboardError(Exception):
    """A real caller-usage error in this module -- never a silently-repaired input."""


# --- dimension auto-gathering (best-effort, disclosed, narrow) --------------

#: `functional_coverage_signoff.py`'s own `status` vocabulary, mapped onto
#: `system_closure_aggregator.py`'s five recognized dimension tokens. Mapped
#: explicitly rather than trusted to that module's alias table, because
#: "SIGNOFF_READY"/"BLOCKED_BY_WAIVER" are not spellings its alias table
#: recognizes -- an unmapped future status value falls back to
#: DIMENSION_UNKNOWN, never a guessed MET.
_FCS_STATUS_TO_DIMENSION: Dict[str, str] = {
    "SIGNOFF_READY": sca.DIMENSION_MET,
    "OPEN": sca.DIMENSION_UNMET,
    "BLOCKED_BY_WAIVER": sca.DIMENSION_UNMET,
    "INCOMPLETE_EVIDENCE": sca.DIMENSION_UNKNOWN,
    "NOT_AVAILABLE": sca.DIMENSION_NOT_AVAILABLE,
}

#: `waiver_store.status_report()`'s own `status` vocabulary, mapped the same
#: explicit way.
_WAIVER_STATUS_TO_DIMENSION: Dict[str, str] = {
    "CLEAR": sca.DIMENSION_MET,
    "WAIVERS_NOT_VALID": sca.DIMENSION_UNMET,
    "NOT_AVAILABLE": sca.DIMENSION_NOT_AVAILABLE,
}

#: Which of the twelve `CLOSURE_DIMENSIONS` this module auto-sources at all.
#: The other ten are honestly left for a caller to supply via
#: `extra_dimension_records` -- never guessed here.
AUTO_SOURCED_DIMENSIONS: Tuple[str, ...] = ("functional_coverage", "waiver_status")


def _gather_functional_coverage_dimension(root: Path, cfg: Optional[Dict[str, Any]]
                                           ) -> Dict[str, Any]:
    if _fcs is None:
        return {"dimension_name": "functional_coverage",
                "status": sca.DIMENSION_UNKNOWN,
                "reason": "functional_coverage_signoff module unavailable (import failed)"}
    try:
        report = _fcs.analyze_functional_coverage_signoff(root, cfg=cfg)
    except Exception as exc:  # a broken input on disk must not crash the dashboard
        return {"dimension_name": "functional_coverage",
                "status": sca.DIMENSION_UNKNOWN,
                "reason": f"functional_coverage_signoff raised: {exc}"}
    status = report.get("status")
    reason = report.get("reason") or (
        f"functional_coverage_signoff Closure={report.get('closure_percent')}% "
        f"({status})")
    return {"dimension_name": "functional_coverage",
            "status": _FCS_STATUS_TO_DIMENSION.get(status, sca.DIMENSION_UNKNOWN),
            "reason": reason}


def _gather_waiver_status_dimension(root: Path) -> Dict[str, Any]:
    if _waiver_store is None:
        return {"dimension_name": "waiver_status",
                "status": sca.DIMENSION_UNKNOWN,
                "reason": "waiver_store module unavailable (import failed)"}
    try:
        report = _waiver_store.status_report(root)
    except Exception as exc:  # a broken ledger on disk must not crash the dashboard
        return {"dimension_name": "waiver_status",
                "status": sca.DIMENSION_UNKNOWN,
                "reason": f"waiver_store raised: {exc}"}
    status = report.get("status")
    if status == "WAIVERS_NOT_VALID":
        bad = [w.get("waiver_id") for w in (report.get("waivers") or [])
               if w.get("status") != "VALID"]
        reason = f"{report.get('not_valid')} waiver(s) not VALID: {bad}"
    elif status == "NOT_AVAILABLE":
        reason = report.get("reason") or "NO_WAIVER_STORE"
    else:
        reason = f"waiver_store.status_report status={status}"
    return {"dimension_name": "waiver_status",
            "status": _WAIVER_STATUS_TO_DIMENSION.get(status, sca.DIMENSION_UNKNOWN),
            "reason": reason}


def gather_closure_dimensions(root: Path, *, cfg: Optional[Dict[str, Any]] = None
                               ) -> List[Dict[str, Any]]:
    """Best-effort, real evidence for exactly the two dimensions named in
    `AUTO_SOURCED_DIMENSIONS`. Never raises -- a broken input source degrades
    that one dimension to DIMENSION_UNKNOWN naming the real reason, and never
    turns an already-computed report into a crash."""
    root = Path(root)
    return [
        _gather_functional_coverage_dimension(root, cfg),
        _gather_waiver_status_dimension(root),
    ]


# --- the composite banner: literal reuse of platform_health.worst() --------

#: `system_closure_aggregator.SYSTEM_CLOSURE_STATUSES` mapped onto
#: `platform_health.HEALTH_STATES` -- never a fifth, invented banner
#: vocabulary. CLOSED never reads HEALTHY unless the platform itself is
#: ALSO measured clean; `platform_health.worst()` (called, not re-derived)
#: is what actually enforces that.
_CLOSURE_STATUS_TO_HEALTH_STATE: Dict[str, str] = {
    sca.CLOSURE_CLOSED: platform_health.HEALTHY,
    sca.CLOSURE_NOT_CLOSED: platform_health.CRITICAL,
    sca.CLOSURE_INCOMPLETE_EVIDENCE: platform_health.UNKNOWN,
}

_BANNER_NOTE: Dict[str, str] = {
    platform_health.HEALTHY: (
        "Both the twelve-dimension closure rollup and the platform health "
        "picture are clean."),
    platform_health.UNKNOWN: (
        "UNKNOWN is not a pass: at least one closure dimension or platform "
        "subsystem has no evidence here, so no GOOD claim is made."),
    platform_health.DEGRADED: (
        "The platform reports a measured DEGRADED subsystem; see Engineering "
        "Detail for which one."),
    platform_health.CRITICAL: (
        "A real blocker exists -- either an UNMET closure dimension or a "
        "CRITICAL platform subsystem; see Engineering Detail for which."),
}


def combine_banner_state(closure_overall_status: str, platform_overall_state: str) -> str:
    """The one worst-wins fold this whole module exists to compute, over
    `platform_health`'s own four-value vocabulary. Never averaged: a real
    platform CRITICAL/DEGRADED can never be diluted by a clean closure
    picture, and a real closure NOT_CLOSED can never be diluted by a clean
    (or merely unmeasured) platform."""
    closure_state = _CLOSURE_STATUS_TO_HEALTH_STATE.get(
        closure_overall_status, platform_health.UNKNOWN)
    return platform_health.worst([closure_state, platform_overall_state])


# --- the combined report -----------------------------------------------------

def derive_executive_engineering_dashboard(
        root, *, cfg: Optional[Dict[str, Any]] = None,
        extra_dimension_records: Optional[Sequence[Dict[str, Any]]] = None,
        window_days: Optional[int] = None) -> Dict[str, Any]:
    """The one call this module exists for: real platform health + real
    twelve-dimension closure, folded into one executive banner plus a full
    engineering drill-down. Read-only end to end -- both `platform_health.
    platform_health_report()` and `system_closure_aggregator.
    aggregate_system_closure()` are, and this function performs no write of
    its own."""
    root = Path(root)
    platform_report = platform_health.platform_health_report(
        root, cfg=cfg, window_days=window_days)

    auto_dims = gather_closure_dimensions(root, cfg=cfg)
    dims: List[Dict[str, Any]] = list(auto_dims)
    if extra_dimension_records:
        dims.extend(dict(r) for r in extra_dimension_records)
    closure_report = sca.aggregate_system_closure(dims)

    banner_state = combine_banner_state(
        closure_report["overall_status"], platform_report["overall_state"])

    clear_dims = [d["dimension_name"] for d in closure_report["dimensions"]
                  if d["normalized_status"] in (sca.DIMENSION_MET, sca.DIMENSION_NOT_APPLICABLE)]
    unhealthy_subsystems = [s["subsystem"] for s in platform_report["subsystems"]
                            if s["state"] != platform_health.HEALTHY]

    executive_summary = {
        "banner_state": banner_state,
        "banner_note": _BANNER_NOTE.get(banner_state, ""),
        "system_closure_status": closure_report["overall_status"],
        "system_closure_reason": closure_report["reason"],
        "platform_overall_state": platform_report["overall_state"],
        "platform_degradation_mode": platform_report.get("degradation_mode"),
        "kpi": {
            "closure_dimensions_clear": len(clear_dims),
            "closure_dimensions_total": len(sca.CLOSURE_DIMENSIONS),
            "closure_dimensions_blocking": list(closure_report["blocking_dimensions"]),
            "closure_dimensions_incomplete": list(closure_report["incomplete_dimensions"]),
            "platform_subsystems_healthy": (
                len(platform_report["subsystems"]) - len(unhealthy_subsystems)),
            "platform_subsystems_total": len(platform_report["subsystems"]),
            "platform_subsystems_unhealthy": unhealthy_subsystems,
        },
    }

    engineering_detail = {
        "closure_dimensions": closure_report["dimensions"],
        "closure_unrecognized_records": closure_report["unrecognized_records"],
        "platform_subsystems": platform_report["subsystems"],
        "platform_error_budgets": platform_report["error_budgets"],
        "platform_window": {
            "window_days": platform_report.get("window_days"),
            "window_start": platform_report.get("window_start"),
            "window_end": platform_report.get("window_end"),
            "window_clock": platform_report.get("window_clock"),
        },
        "platform_unmeasurable_slis": platform_report.get("unmeasurable_slis"),
    }

    auto_dim_names = {d["dimension_name"] for d in auto_dims}
    return {
        "project_root": str(root),
        "executive_summary": executive_summary,
        "engineering_detail": engineering_detail,
        "dimension_gathering": {
            "auto_sourced_dimensions": sorted(auto_dim_names),
            "caller_supplied_dimensions": sorted(
                {r.get("dimension_name") for r in (extra_dimension_records or [])
                 if isinstance(r, dict) and r.get("dimension_name")}),
            "not_supplied_dimensions": sorted(
                set(sca.CLOSURE_DIMENSIONS) - auto_dim_names
                - {r.get("dimension_name") for r in (extra_dimension_records or [])
                   if isinstance(r, dict)}),
        },
        "fact_sources": [
            "dv_harness.platform_health.platform_health_report",
            "dv_harness.system_closure_aggregator.aggregate_system_closure",
            "dv_harness.functional_coverage_signoff.analyze_functional_coverage_signoff",
            "dv_harness.waiver_store.status_report",
        ],
        "authorizes_nothing": ("read-only rollup + render: no stage run, no build, "
                               "no LSF submission, no approval consulted or granted"),
    }


# --- rendering ----------------------------------------------------------------

#: A literal, disclosed copy of dashboard.py's own `.card`/`.tiles`/`.tile`
#: container rules plus its PASS/FAIL/PARTIAL/UNKNOWN hex palette (as of
#: this writing) -- see this module's own docstring for why a functional
#: import of dashboard.py itself is neither needed nor appropriate here.
_CARD_CSS = """
body{font-family:Arial,sans-serif;background:#f4f7fb;color:#18233f;margin:0}
header{background:#18233f;color:white;padding:18px 28px}
main{padding:24px;max-width:1200px;margin:auto}
.card{background:white;border:1px solid #d9e1ec;border-radius:10px;padding:16px;margin-bottom:16px}
.tiles{display:flex;flex-wrap:wrap;gap:12px}
.tile{flex:1;min-width:100px;background:#f7f9fc;border:1px solid #e3e9f2;border-radius:8px;padding:10px 14px;text-align:center}
.tile .n{font-size:22px;font-weight:bold}
.tile .l{font-size:11px;color:#5a6b8c;text-transform:uppercase;letter-spacing:.03em}
.note{color:#8a97b3;font-size:12px}
.err{color:#b84444}
.ok{color:#25845b}
.warn{color:#b8862f}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid #edf1f5}
th{color:#5a6b8c;text-transform:uppercase;font-size:11px;letter-spacing:.03em}
/* platform_health.HEALTH_STATES palette, reusing dashboard.py's own
   PASS/PARTIAL/FAIL/UNKNOWN colors (#25845b/#b36a00/#b84444/#9aa6bd). */
.state-HEALTHY{color:#25845b;font-weight:bold}
.state-DEGRADED{color:#b36a00;font-weight:bold}
.state-CRITICAL{color:#b84444;font-weight:bold}
.state-UNKNOWN{color:#9aa6bd;font-weight:bold}
.banner{font-size:28px;padding:10px 0}
"""

#: system_closure_aggregator dimension statuses -> one of the four state-*
#: CSS classes above, using the same green/red/grey convention this whole
#: module already applies to the platform-health side.
_DIMENSION_STATUS_TO_CSS: Dict[str, str] = {
    sca.DIMENSION_MET: "state-HEALTHY",
    sca.DIMENSION_NOT_APPLICABLE: "state-HEALTHY",
    sca.DIMENSION_UNMET: "state-CRITICAL",
    sca.DIMENSION_UNKNOWN: "state-UNKNOWN",
    sca.DIMENSION_NOT_AVAILABLE: "state-UNKNOWN",
    sca.DIMENSION_NOT_SUPPLIED: "state-UNKNOWN",
    sca.DIMENSION_AMBIGUOUS_CONFLICTING_SUBMISSIONS: "state-DEGRADED",
}


def _esc(value: Any) -> str:
    text = "" if value is None else str(value)
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                .replace('"', "&quot;"))


def render_dashboard_html(data: Dict[str, Any]) -> str:
    """A standalone HTML snapshot: an Executive Summary card, then an
    Engineering Detail card carrying the full twelve-dimension and
    per-subsystem drill-down. No JS polling -- this is a rendered snapshot
    of `derive_executive_engineering_dashboard()`'s own result, not a live
    server (dashboard.py already owns that machinery; this module is
    deliberately not a second one)."""
    ex = data["executive_summary"]
    eng = data["engineering_detail"]
    banner_cls = f"state-{ex['banner_state']}"

    kpi_tiles = "".join(
        f'<div class="tile"><div class="n">{_esc(v)}</div><div class="l">{_esc(l)}</div></div>'
        for v, l in [
            (f"{ex['kpi']['closure_dimensions_clear']}/{ex['kpi']['closure_dimensions_total']}",
             "Closure dims clear"),
            (f"{ex['kpi']['platform_subsystems_healthy']}/{ex['kpi']['platform_subsystems_total']}",
             "Subsystems healthy"),
            (ex["system_closure_status"], "System closure"),
            (ex["platform_overall_state"], "Platform state"),
        ])

    blocking = ", ".join(ex["kpi"]["closure_dimensions_blocking"]) or "(none)"
    incomplete = ", ".join(ex["kpi"]["closure_dimensions_incomplete"]) or "(none)"
    unhealthy = ", ".join(ex["kpi"]["platform_subsystems_unhealthy"]) or "(none)"

    dim_rows = "".join(
        f'<tr><td>{_esc(d["dimension_name"])}</td>'
        f'<td class="{_DIMENSION_STATUS_TO_CSS.get(d["normalized_status"], "state-UNKNOWN")}">'
        f'{_esc(d["normalized_status"])}</td>'
        f'<td>{_esc(d.get("supplied"))}</td>'
        f'<td>{_esc("; ".join(d.get("reasons") or []))}</td></tr>'
        for d in eng["closure_dimensions"])

    subsystem_rows = "".join(
        f'<tr><td>{_esc(s["subsystem"])}</td>'
        f'<td class="state-{_esc(s["state"])}">{_esc(s["state"])}</td>'
        f'<td>{_esc(s["reason"])}</td><td class="note">{_esc(s["fact_source"])}</td></tr>'
        for s in eng["platform_subsystems"])

    budget_rows = "".join(
        f'<tr><td>{_esc(b["slo_id"])}</td><td>{_esc(b["status"])}</td>'
        f'<td>{_esc(b.get("achieved_percent"))}</td>'
        f'<td>{_esc(b.get("budget_remaining_percent"))}</td></tr>'
        for b in eng["platform_error_budgets"])

    gathering = data["dimension_gathering"]
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Executive + Engineering Dashboard</title>
<style>{_CARD_CSS}</style></head>
<body>
<header><h2>Executive + Engineering Dashboard</h2>
<div class="note">{_esc(data["project_root"])}</div></header>
<main>
<div class="card" id="execSummaryCard">
<h3>Executive Summary</h3>
<div class="banner {banner_cls}">{_esc(ex["banner_state"])}</div>
<div class="note">{_esc(ex["banner_note"])}</div>
<div class="tiles">{kpi_tiles}</div>
<div class="note" style="margin-top:8px">
Blocking closure dimensions: {_esc(blocking)}<br>
Incomplete-evidence closure dimensions: {_esc(incomplete)}<br>
Unhealthy platform subsystems: {_esc(unhealthy)}
</div>
</div>
<div class="card" id="engDetailCard">
<h3>Engineering Detail -- Twelve-Dimension Closure Rollup</h3>
<div class="note">Auto-sourced: {_esc(", ".join(gathering["auto_sourced_dimensions"]) or "(none)")}
 -- Not supplied (honest gap): {_esc(", ".join(gathering["not_supplied_dimensions"]) or "(none)")}</div>
<table><tr><th>Dimension</th><th>Status</th><th>Supplied</th><th>Reason(s)</th></tr>
{dim_rows}
</table>
</div>
<div class="card" id="engPlatformCard">
<h3>Engineering Detail -- Platform Subsystem Health</h3>
<table><tr><th>Subsystem</th><th>State</th><th>Reason</th><th>Fact source</th></tr>
{subsystem_rows}
</table>
<h3 style="margin-top:16px">Error Budgets</h3>
<table><tr><th>SLO</th><th>Status</th><th>Achieved %</th><th>Budget remaining %</th></tr>
{budget_rows}
</table>
</div>
<div class="note">{_esc(data["authorizes_nothing"])}</div>
</main>
</body></html>"""


def render_dashboard_text(data: Dict[str, Any]) -> str:
    ex = data["executive_summary"]
    eng = data["engineering_detail"]
    lines = [
        f"Executive + Engineering Dashboard ({data['project_root']})",
        f"EXECUTIVE SUMMARY: {ex['banner_state']}   {ex['banner_note']}",
        f"  system_closure_status={ex['system_closure_status']}  "
        f"platform_overall_state={ex['platform_overall_state']}",
        f"  closure dims clear: {ex['kpi']['closure_dimensions_clear']}/"
        f"{ex['kpi']['closure_dimensions_total']}   "
        f"subsystems healthy: {ex['kpi']['platform_subsystems_healthy']}/"
        f"{ex['kpi']['platform_subsystems_total']}",
        "", "ENGINEERING DETAIL -- closure dimensions", "-" * 78,
    ]
    for d in eng["closure_dimensions"]:
        lines.append(f"- {d['dimension_name']:<24}{d['normalized_status']:<14}"
                     f"{'; '.join(d.get('reasons') or [])}")
    lines += ["", "ENGINEERING DETAIL -- platform subsystems", "-" * 78]
    for s in eng["platform_subsystems"]:
        lines.append(f"- {s['subsystem']:<24}{s['state']:<10}{s['reason']}")
    lines += ["", data["authorizes_nothing"]]
    return "\n".join(lines)


# --- CLI front door -------------------------------------------------------
# No `dv-harness` verb was added here. `dashboard.py`, `cli.py` and `gates.py`
# were all under active concurrent edit in this session at write time (the
# most recently modified files in the whole `dv_harness/` package) -- per
# this task's own house rule, this module stays a standalone
# `python -m dv_harness.exec_eng_dashboard` front door, matching several
# other same-day modules that made the identical disclosed choice.

EXIT_OK = 0
#: Same convention `platform_health.py` already uses: DEGRADED/CRITICAL exit
#: non-zero; UNKNOWN does not (it is an honest admission of missing
#: evidence, never an alert and never a fabricated pass).
EXIT_ATTENTION = 2


def execute(root, *, cfg: Optional[Dict[str, Any]] = None,
            extra_dimension_records: Optional[Sequence[Dict[str, Any]]] = None,
            window_days: Optional[int] = None) -> Tuple[int, Dict[str, Any], str, str]:
    """(exit_code, data, text, html) -- the one shared implementation behind
    `python -m dv_harness.exec_eng_dashboard`."""
    data = derive_executive_engineering_dashboard(
        root, cfg=cfg, extra_dimension_records=extra_dimension_records,
        window_days=window_days)
    banner = data["executive_summary"]["banner_state"]
    code = EXIT_ATTENTION if banner in (platform_health.DEGRADED, platform_health.CRITICAL) else EXIT_OK
    return code, data, render_dashboard_text(data), render_dashboard_html(data)


def main(argv: Optional[List[str]] = None) -> int:  # pragma: no cover - CLI shim
    import argparse
    import sys

    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.exec_eng_dashboard",
        description="Executive Summary + Engineering Detail dashboard, combining "
                    "system_closure_aggregator's twelve-dimension closure rollup and "
                    "platform_health's subsystem health. Read-only.")
    ap.add_argument("--root", default=".")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out", default=None, help="write the rendered HTML page to this path")
    ap.add_argument("--window-days", type=int, default=None)
    args = ap.parse_args(argv)

    code, data, text, html = execute(args.root, window_days=args.window_days)
    if args.out:
        Path(args.out).write_text(html, encoding="utf-8")
        print(f"wrote {args.out}")
    if args.json:
        print(json.dumps(data, indent=2, default=str))
    else:
        print(text)
    return code


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(main())
