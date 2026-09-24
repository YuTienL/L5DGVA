from __future__ import annotations
import base64, binascii, json, os, re, tempfile, threading, time, traceback, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence
from .config import load_config, save_config
from .regression_reporter import load_jobs, get_job
from .gates import extract_evidence_blocks, JUDGMENT_FIELDS, CCL_SKIPPABLE, REVIEWER_CONFIDENCE_LEVELS, _iter_judgment_targets
from .storage import _atomic_replace
from .control_plane import ControlPlane, describe_stage, describe_stages
from . import dashboard_auth
from . import gui_audit_log


def _access_user() -> str:
    # Same fallback chain as cli.py's own private copy (for the equivalent
    # CLI_ACCESS event) -- kept separate rather than a cross-module import,
    # matching this codebase's established pattern (control_plane.py/
    # knowledge_center.py each keep their own copy too).
    return os.environ.get("USER") or os.environ.get("USERNAME") or "unknown"


def _access_host() -> str:
    return os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME") or "unknown-host"


def _read_json_file(path: Path, default: Any = None) -> Any:
    """json.loads(path.read_text()) hardened against the same Windows
    concurrent-reader-vs-os.replace() race storage._atomic_replace's
    docstring describes, from the OTHER side: this dashboard's GET handlers
    now poll state.json/project_meta.json every few seconds from an HTTP
    thread WHILE a background POST /api/start run (or a concurrent
    POST /api/control) actively os.replace()s the same file on another
    thread in this same process. A reader's CreateFile can transiently lose
    that race with WinError/Errno 5 (PermissionError) even though the
    replace itself is already retried/atomic -- retry the read rather than
    letting one unlucky poll surface as a 500 (or an inconsistent True->False
    'not found' read) to the frontend. No behavior change on POSIX, where
    os.replace() has no such window."""
    for attempt in range(10):
        try:
            if not path.exists():
                return default
            return json.loads(path.read_text(encoding="utf-8"))
        except PermissionError:
            time.sleep(0.02 * (attempt + 1))
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))

HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>DV Agent Harness</title>
<style>
body{font-family:Arial,sans-serif;background:#f4f7fb;color:#18233f;margin:0}
header{background:#18233f;color:white;padding:18px 28px}
main{padding:24px;max-width:1200px;margin:auto}
.card{background:white;border:1px solid #d9e1ec;border-radius:10px;padding:16px;margin-bottom:16px}
.tiles{display:flex;flex-wrap:wrap;gap:12px}
.tile{flex:1;min-width:100px;background:#f7f9fc;border:1px solid #e3e9f2;border-radius:8px;padding:10px 14px;text-align:center}
.tile .n{font-size:22px;font-weight:bold}
.tile .l{font-size:11px;color:#5a6b8c;text-transform:uppercase;letter-spacing:.03em}
.bar{background:#e3e9f2;border-radius:6px;height:10px;overflow:hidden;margin-top:6px}
.bar>div{background:#2457a6;height:100%}
.node{display:grid;grid-template-columns:22px 220px 1fr;gap:8px;padding:6px 4px;border-bottom:1px solid #edf1f5;align-items:center;font-size:13px}
.node.here{background:#eef4ff;border-radius:6px}
.icon{font-weight:bold}
.PASS,.CLOSED,.SCRIPT_SMOKE_PASS,.COMPLETED{color:#25845b}.FAIL,.BLOCKED,.SCRIPT_SMOKE_FAIL,.FAILED{color:#b84444}
.RUNNING,.RETRY{color:#2457a6}.PARTIAL,.WAIT_USER,.NO_SOURCE_DATA,.GATE_TOOL_MISSING{color:#b36a00}.NOT_STARTED{color:#9aa6bd}
/* amba_fabric_discovery.BIND_READINESS_VALUES: READY/PARTIAL/BLOCKED/UNKNOWN.
   PARTIAL and BLOCKED already have a color above (same words, same meaning);
   these two are the readiness-only values. */
.READY{color:#25845b}.UNKNOWN{color:#9aa6bd}
/* capability_evolution.PROMOTION_STATES / RECOMMENDATIONS. Deliberately share
   no token with models.Status (assert_no_verification_verdict_vocabulary()),
   so these are their own classes and can never be styled as a DUT verdict. */
.HUMAN_APPROVED,.PRODUCTION,.KEEP{color:#25845b}
.REJECTED,.ROLLED_BACK{color:#b84444}
.PROMOTION_CANDIDATE,.BENCHMARKED,.ADD{color:#2457a6}
.DISCOVERED,.EVIDENCE_GATHERING,.PROPOSED,.EXPERIMENT_APPROVED,.EXPERIMENTING,.ENHANCE,.EXPERIMENT{color:#b36a00}
.protoTile{cursor:pointer}.protoTile:hover{border-color:#2457a6}.protoTile.selected{border-color:#2457a6;background:#eaf1fb}
.modeTile.mode-selected{border-color:#2457a6;background:#eaf1fb}
.tier-reached{border-color:#25845b;background:#e3f7ea}.tier-unreached{opacity:.5}
.cap-generic-only{color:#b8843a}.cap-model{color:#2457a6}.cap-dut-proven{color:#25845b;font-weight:600}
code{background:#eef2f7;padding:3px 5px}
.note{color:#8a97b3;font-size:12px}
.err{color:#b84444}
.ok{color:#25845b}
/* A third severity, distinct from .err: the Loop Engineering Center's
   LOOP_BUDGET_WARNING is "the next failure exhausts this budget", which is not
   yet a failure and must not read as one. */
.warn{color:#b8862f}
.ctrlrow{margin:8px 0;display:flex;flex-wrap:wrap;gap:8px;align-items:center;font-size:13px}
.ctrlrow input[type=text],.ctrlrow input:not([type]),.ctrlrow select{padding:4px 6px;border:1px solid #d9e1ec;border-radius:5px}
.ctrlrow label{display:flex;align-items:center;gap:4px}
button{background:#2457a6;color:white;border:none;border-radius:6px;padding:6px 12px;cursor:pointer;font-size:13px}
button:disabled{background:#b7c3d9;cursor:not-allowed}
button.secondary{background:#5a6b8c}
input,select{font-size:13px}
#controlResult,#setupResult,#runResult,#researchResult{background:#f7f9fc;border:1px solid #e3e9f2;border-radius:6px;padding:8px;white-space:pre-wrap;font-size:12px;margin-top:8px;min-height:14px}
/* "Just transitioned" banner (2026-09-01, runtime-progress-visibility pass):
   a real, always-visible "Last transition: <stage> -> <status> at <time>"
   line sourced from state.json's last_transition (set by engine.run_stage()
   every time a stage reaches a terminal status) -- deliberately ALWAYS
   rendered (never a time-limited flash that disappears on its own) so a
   viewer who opens the dashboard minutes after the fact still sees it, not
   just someone watching the exact moment it fired. See the RULING comment
   in load()'s renderLastTransitionBanner() call site for why. */
.transitionBanner{border-radius:8px;padding:10px 16px;margin-bottom:16px;font-size:13px;border:1px solid;display:flex;align-items:center;gap:10px}
.transitionBanner .label{font-weight:bold;text-transform:uppercase;font-size:11px;letter-spacing:.03em}
.transitionBanner.status-PASS,.transitionBanner.status-CLOSED{background:#e3f7ea;border-color:#25845b;color:#184a33}
.transitionBanner.status-FAIL,.transitionBanner.status-BLOCKED{background:#fbe7e7;border-color:#b84444;color:#6e2323}
.transitionBanner.status-PARTIAL,.transitionBanner.status-WAIT_USER{background:#fdf1e0;border-color:#b36a00;color:#6e4300}
.transitionBanner.status-RUNNING,.transitionBanner.status-RETRY{background:#e8f0fb;border-color:#2457a6;color:#1b3c73}
.transitionBanner.status-none{background:#f4f7fb;border-color:#d9e1ec;color:#5a6b8c}
/* Global Status Bar (Global Status Bar theme, sections 414-421/428): a
   persistent header, always rendered above <main> so it is visible on
   every scroll position of this single-page dashboard, reading ONE real
   HarnessStatusIR snapshot via GET /api/status
   (harness_status.HarnessStatusService.serve()) -- never a second,
   dashboard-local aggregation of harness state. Three layout modes
   (compact/standard/expanded) control how many of the five summary
   regions (identity/harness/current-activity/execution/closure+blockers)
   are shown in the always-visible row; a click-to-expand drawer (any
   layout mode) renders every one of the IR's eleven sections in full. */
.statusBar{position:sticky;top:0;z-index:50;background:#12203a;color:#eaf1fb;padding:8px 16px;font-size:12px;box-shadow:0 2px 6px rgba(0,0,0,.15)}
.statusBar .statusBarRow{display:flex;align-items:center;gap:14px;flex-wrap:wrap}
.statusBar .sbRegion{display:flex;align-items:center;gap:6px}
.statusBar .sbLabel{color:#9fb4d6;font-size:10px;text-transform:uppercase;letter-spacing:.03em}
.statusBar button{background:#1b3a63;color:#eaf1fb;border:1px solid #2c5490;border-radius:4px;padding:3px 8px;font-size:11px;cursor:pointer}
.statusBar .sbSpacer{flex:1 1 auto}
.sbPill{border-radius:10px;padding:2px 9px;font-weight:bold;font-size:11px;white-space:nowrap}
.sbPill.status-READY,.sbPill.status-SIGNOFF_READY{background:#25845b;color:#fff}
.sbPill.status-PARTIAL,.sbPill.status-CONVERGING,.sbPill.status-RUNNING,.sbPill.status-VERIFYING{background:#b36a00;color:#fff}
.sbPill.status-BLOCKED,.sbPill.status-FAILED{background:#b84444;color:#fff}
.sbPill.status-HUMAN_GATE,.sbPill.status-WAITING,.sbPill.status-STALE,.sbPill.status-RETRY_WAIT,.sbPill.status-BUDGET_EXHAUSTED,.sbPill.status-OSCILLATING,.sbPill.status-PLATEAU{background:#6a4fa0;color:#fff}
.sbPill.status-UNKNOWN,.sbPill.status-IDLE,.sbPill.status-CANCELLED,.sbPill.status-NOT_APPLICABLE{background:#5a6b8c;color:#fff}
/* compact mode: identity + overall harness state only */
.statusBar.mode-compact #sbActivityRegion,.statusBar.mode-compact #sbExecutionRegion,.statusBar.mode-compact #sbClosureRegion,.statusBar.mode-compact #sbBlockersRegion{display:none}
.statusBarDrawer{margin-top:8px;background:#0e1a30;border-top:1px solid #2c5490;padding:8px 4px;display:flex;flex-wrap:wrap;gap:16px;max-height:320px;overflow:auto}
.statusBarDrawerSection{min-width:190px;font-size:11px}
.statusBarDrawerSection h4{margin:0 0 4px 0;font-size:11px;text-transform:uppercase;letter-spacing:.03em;color:#9fb4d6}
.statusBarDrawerSection .err{color:#ff9a9a}
</style></head>
<body><header><h2>DV Agent Harness L5</h2></header>
<div class="statusBar mode-standard" id="globalStatusBar">
  <div class="statusBarRow">
    <div class="sbRegion" id="sbIdentityRegion"><span class="sbLabel">Project</span><span id="sbIdentity">-</span></div>
    <div class="sbRegion" id="sbHarnessRegion"><span class="sbLabel">Harness</span><span id="sbHarness" class="sbPill status-UNKNOWN">UNKNOWN</span></div>
    <div class="sbRegion" id="sbActivityRegion"><span class="sbLabel">Activity</span><span id="sbActivity">-</span></div>
    <div class="sbRegion" id="sbExecutionRegion"><span class="sbLabel">Execution</span><span id="sbExecution">-</span></div>
    <div class="sbRegion" id="sbClosureRegion"><span class="sbLabel">Closure</span><span id="sbClosure" class="sbPill status-UNKNOWN">UNKNOWN</span></div>
    <div class="sbRegion" id="sbBlockersRegion"><span class="sbLabel">Blockers</span><span id="sbBlockers">-</span></div>
    <div class="sbSpacer"></div>
    <button onclick="cycleStatusBarLayout()" id="sbLayoutBtn" title="Cycle compact/standard/expanded layout">Standard</button>
    <button onclick="toggleStatusBarDrawer()" id="sbDrawerBtn" title="Show every HarnessStatusIR field">Details &#9662;</button>
  </div>
  <div class="statusBarDrawer" id="statusBarDrawer" style="display:none"></div>
</div>
<main>
<div id="authBanner" style="display:none;background:#fdecea;border:1px solid #f5c2bd;color:#8a1c10;border-radius:8px;padding:12px 14px;margin-bottom:16px;font-size:13px"></div>
<div class="transitionBanner status-none" id="lastTransitionBanner"><span class="label">Last transition</span><span id="lastTransitionText">no stage has completed yet this run</span></div>
<div class="card" id="setupCard" style="display:none">
<h3>Setup</h3>
<div class="note">Record this project's Linux DB/handoff path and its own working path (descriptive metadata -- the harness will not start from this dashboard until both are saved).</div>
<div class="ctrlrow"><label>DB Path <input id="dbPathInput" size="40" placeholder="/path/on/linux/db"></label></div>
<div class="ctrlrow"><label>Working Path <input id="workingPathInput" size="40" placeholder="/path/on/linux/working"></label></div>
<div class="ctrlrow"><button onclick="doSetup()">Save</button></div>
<div id="setupResult"></div>
</div>

<div class="card" id="uploadsCard"><h3>Intake Uploads</h3>
<div class="note">Upload real evidence files into <code>.dv-harness/uploads/&lt;category&gt;/</code> for the 5
intake categories CLAUDE.md / intake_readiness.py look for (Spec, RTL/interface files, existing
command.txt patterns, VIP reference material, DE local-sim results). A filename collision within a
category gets a numeric suffix -- never a silent overwrite.</div>
<div class="ctrlrow"><label style="min-width:120px">Spec</label><input type="file" id="uploadFile_spec"><button onclick="doUpload('spec')">Upload</button></div>
<div class="ctrlrow"><label style="min-width:120px">RTL / Interface</label><input type="file" id="uploadFile_rtl"><button onclick="doUpload('rtl')">Upload</button></div>
<div class="ctrlrow"><label style="min-width:120px">command.txt</label><input type="file" id="uploadFile_command_txt"><button onclick="doUpload('command_txt')">Upload</button></div>
<div class="ctrlrow"><label style="min-width:120px">VIP Reference</label><input type="file" id="uploadFile_vip_reference"><button onclick="doUpload('vip_reference')">Upload</button></div>
<div class="ctrlrow"><label style="min-width:120px">DE Local Sim</label><input type="file" id="uploadFile_de_sim"><button onclick="doUpload('de_sim')">Upload</button></div>
<div id="uploadResult"></div>
<div class="note" style="margin-top:8px">Currently uploaded (real files on disk, from GET /api/state's <code>uploaded_files</code>):</div>
<div id="uploadedFilesList" style="font-size:12px;margin-top:4px"></div>
</div>

<div class="card"><h3>Status</h3><div id="tiles" class="tiles"></div>
<div class="bar"><div id="progressbar" style="width:0%"></div></div></div>
<div class="card"><h3>Control Plane</h3><div id="cptiles" class="tiles"></div>
<div class="note" id="constraintList" style="margin-top:8px"></div></div>
<div class="card"><h3>Why (current stage)</h3>
<div class="note">Real per-run blocking_reason/gate_verdict for the current stage -- not the static explainer below.
Stage completion percent and the entry/exit evidence checklist below come from the same
<code>control_plane.describe_stage()</code> data the CLI's <code>explain</code>/<code>evidence</code>/<code>checklist</code>
subcommands print. The Evidence provenance block names who produced each headline dynamic-behaviour
claim (deadlock/livelock, starvation, fairness, interrupt latency, scoreboard liveness); an
<code>AGENT_SELF_ATTESTED</code> claim is shown in red and is NOT independently derived evidence.</div>
<div id="stageWhy" style="margin-top:8px"></div></div>
<div class="card"><h3>LSF</h3><div id="lsftiles" class="tiles"></div>
<div class="note" style="margin-top:8px">Per-job drill-down (GET /api/lsf/jobs[/&lt;job_id&gt;], CLI <code>dv-harness lsf [job_id]</code>). Click a row to expand its full detail. Read-only here: real job submission/kill/reconciliation against LSF (<code>dv-harness lsf-submit</code>/<code>lsf-kill</code>/<code>lsf-reconcile</code>, wrapping real <code>bsub</code>/<code>bkill</code>/<code>bjobs</code>) is CLI-only today.</div>
<div style="overflow-x:auto"><table id="jobsTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:6px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">Job</th><th style="padding:4px">Pattern</th><th style="padding:4px">LSF</th>
<th style="padding:4px">DV Analysis</th><th style="padding:4px">UVM_ERR</th><th style="padding:4px">UVM_FATAL</th></tr></thead>
<tbody id="jobsTableBody"></tbody></table></div>
<pre id="jobDetail" style="display:none;white-space:pre-wrap;font-size:12px;background:#f7f9fc;border:1px solid #e3e9f2;border-radius:6px;padding:8px;margin-top:8px"></pre>
</div>
<div class="card"><h3>Findings</h3><div id="findtiles" class="tiles"></div></div>
<div class="card" id="coverageCard"><h3>Coverage Analysis</h3>
<div class="note">Real per-category coverage holes (GET /api/coverage, reading
<code>.dv-harness/coverage/summary.json</code> -- a JSON reduction of whatever real
coverage tool this project uses, per <code>coverage_analysis.py</code>'s own docstring),
sorted worst-first via <code>identify_holes()</code>. No summary file yet shows an
honest empty state below, never a fabricated percent.</div>
<div style="overflow-x:auto"><table id="coverageHolesTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:6px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">Category</th><th style="padding:4px">Percent</th>
<th style="padding:4px">Bins Hit/Total</th><th style="padding:4px">Bins Missing</th></tr></thead>
<tbody id="coverageHolesTableBody"></tbody></table></div>
<div class="note" id="coverageTrendNote" style="margin-top:8px"></div>
<div id="coverageTrendChart" style="margin-top:6px"></div>
</div>
<div class="card" id="ambaFabricCard"><h3>AMBA Fabric / VIP Bind / Scoreboard</h3>
<div class="note">Real AMBA-22 <code>AMBA_PORT_REGISTRY</code> rows (GET /api/amba, reading
<code>.dv-harness/amba/amba_port_registry.json</code> through
<code>amba_port_registry.load_amba_port_registry()</code>): one row per discovered fabric port, every
column read off the AMBA-16 matrix / AMBA-15 width checklist / AMBA-20 VIP plan / AMBA-21 scoreboard
ingress map those modules already produced -- never re-derived here. Traced masters/slaves and the
unresolved list come from the same module's <code>registry_endpoints()</code>. No registry file yet
shows an honest empty state below, never a fabricated port; a registry failing that module's own
<code>assert_registry_complete()</code> reports its real reason/detail instead.
<b>Discovery and planning only</b> (AMBA-30 / AMBA-31): every <code>vip_bind_hierarchy</code> below is
a PROPOSED location a human reviews -- this card is read-only and neither shows nor emits any
SystemVerilog <code>bind</code> statement.</div>
<div id="ambaTiles" class="tiles" style="margin-top:8px"></div>
<div class="ctrlrow" style="margin-top:6px"><label>Filter by port / hierarchy
  <input id="ambaPortFilter" size="26" oninput="renderAmbaTable()" placeholder="substring filter"></label></div>
<div style="overflow-x:auto"><table id="ambaTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:6px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">Port</th><th style="padding:4px">Protocol</th><th style="padding:4px">Fabric Role</th>
<th style="padding:4px">Endpoint (traced)</th><th style="padding:4px">Proposed VIP Bind</th>
<th style="padding:4px">VIP Mode</th><th style="padding:4px">Scoreboard Channel</th>
<th style="padding:4px">Trace Status</th><th style="padding:4px">Readiness</th>
<th style="padding:4px">Confidence</th></tr></thead>
<tbody id="ambaTableBody"></tbody></table></div>
<div class="note" id="ambaUnresolvedNote" style="margin-top:8px"></div>
</div>

<div class="card" id="ambaConnectivityMatrixCard"><h3>AMBA Fabric Connectivity Matrix</h3>
<div class="note">Real <code>AMBAFabricGraphIR</code> node/edge topology (GET /api/amba-connectivity-matrix,
reading <code>.dv-harness/amba/amba_fabric_graph.json</code> through
<code>amba_fabric_graph_ir.build_amba_fabric_graph()</code>): every node's id/kind and every edge's
from/to endpoint, exactly as that module's own twelve-kind fabric-component vocabulary and required
evidence citations validated them -- never re-derived here. A <code>reconfigurable</code>/<code>dynamic</code>
node claim reaching this table already cleared that module's own grounded-evidence check
(<code>assert_no_ungrounded_reconfigurable_claim()</code>). No declared graph yet shows an honest empty
state below, never a fabricated node or edge; a graph that module refuses to build (an unknown kind,
missing evidence, an edge naming an undeclared node, an ungrounded reconfigurable claim) reports its
real <code>AMBAFabricGraphError</code> code/detail instead of a generic 500. <b>Read-only</b>: this card
runs no build, simulation, or gate, and writes no topology decision.</div>
<div id="ambaConnectivityMatrixTiles" class="tiles" style="margin-top:8px"></div>
<div style="overflow-x:auto"><table id="ambaConnectivityMatrixNodesTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:6px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">Node</th><th style="padding:4px">Kind</th><th style="padding:4px">Reconfigurable</th>
<th style="padding:4px">Evidence</th></tr></thead>
<tbody id="ambaConnectivityMatrixNodesBody"></tbody></table></div>
<div style="overflow-x:auto"><table id="ambaConnectivityMatrixEdgesTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:6px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">From</th><th style="padding:4px">To</th><th style="padding:4px">Evidence</th></tr></thead>
<tbody id="ambaConnectivityMatrixEdgesBody"></tbody></table></div>
</div>

<div class="card" id="ambaPathExplorerCard"><h3>AMBA Path Explorer</h3>
<div class="note">Pick a (master, slave) pair and see <code>amba_fabric_graph_ir.py</code>'s real declared
route(s) for it (GET /api/amba-path-explorer, reading the SAME <code>.dv-harness/amba/amba_fabric_graph.json</code>
document -- widened with an optional <code>"routes"</code> list -- through
<code>amba_fabric_graph_ir.build_amba_path_ir()</code>): every distinct declared route for the pair is shown,
never collapsed to one, and each route's own hop sequence is cross-checked against the real fabric graph
exactly as that module computed it (<code>CONSISTENT_WITH_GRAPH</code> / <code>INCONSISTENT_WITH_GRAPH</code> /
<code>CONSISTENCY_NOT_CHECKED</code>). No graph yet, or a pair nobody declared a route for, shows an honest
empty state -- never a fabricated route. <b>Read-only</b>: this card runs no build, simulation, or gate.</div>
<div class="ctrlrow" style="margin-top:6px">
  <label>Master <select id="ambaPathMaster" onchange="onAmbaPathMasterChange()"></select></label>
  <label>Slave <select id="ambaPathSlave" onchange="loadAmbaPathExplorerRoutes()"></select></label>
</div>
<div id="ambaPathExplorerTiles" class="tiles" style="margin-top:8px"></div>
<div style="overflow-x:auto"><table id="ambaPathExplorerTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:6px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">Route</th><th style="padding:4px">Hops</th><th style="padding:4px">Graph Consistency</th>
<th style="padding:4px">Findings</th><th style="padding:4px">Evidence</th></tr></thead>
<tbody id="ambaPathExplorerBody"></tbody></table></div>
</div>

<div class="card" id="ambaBottleneckCard"><h3>AMBA Bottleneck Analysis</h3>
<div class="note">Real <code>amba_performance_classification.identify_bottleneck_candidate()</code> records
(GET /api/amba-bottleneck, reading <code>.dv-harness/amba/bottleneck_candidates.json</code>): each row
is a structured <b>Hypothesis -&gt; Evidence -&gt; Confidence -&gt; Gap -&gt; Next-Best-Action</b> candidate
-- NEVER a bare label, and never a confirmed root cause. A declared candidate carrying fewer than the
required 2 real correlated evidence citations is refused by that module and shown below under
"Rejected declarations" instead of a fabricated candidate. No declared candidates yet shows an honest
empty state. <b>Read-only</b>: this card runs no build, simulation, or gate, and decides no root cause
-- confidence is capped at MEDIUM whenever a real unresolved gap is declared.</div>
<div id="ambaBottleneckTiles" class="tiles" style="margin-top:8px"></div>
<div style="overflow-x:auto"><table id="ambaBottleneckTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:6px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">Hypothesis</th><th style="padding:4px">Evidence</th><th style="padding:4px">Confidence</th>
<th style="padding:4px">Gap</th><th style="padding:4px">Next-Best-Action</th></tr></thead>
<tbody id="ambaBottleneckBody"></tbody></table></div>
<div class="note" id="ambaBottleneckRejectedNote" style="margin-top:8px"></div>
</div>

<div class="card" id="ambaPerfCenterCard"><h3>AMBA Per-Port Performance Center</h3>
<div class="note">Real <code>amba_performance_calculator.aggregate_port_performance()</code> results
(GET /api/amba-performance, reading <code>.dv-harness/amba/performance_samples.json</code>): every
bandwidth/throughput/latency-percentile/outstanding/stall-ratio/utilization/bandwidth-utilization cell
is a real <code>PortPerformanceIR</code>/<code>PathPerformanceIR</code> field, with its own
<code>COMPUTED</code>/<code>UNKNOWN</code>/<code>NOT_APPLICABLE</code> status shown honestly -- a
metric this project has not supplied real samples/peak-bandwidth for renders as
<b>UNKNOWN</b>/<b>NOT_APPLICABLE</b> with the real reason, never a fabricated number. No declared
samples file yet shows an honest empty state. <b>Read-only</b>: this card runs no build, simulation,
or gate, and this harness owns no live simulator -- every number shown is caller-supplied evidence,
never estimated.</div>
<div id="ambaPerfPortTiles" class="tiles" style="margin-top:8px"></div>
<div style="overflow-x:auto"><table id="ambaPerfPortTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:6px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">Port</th><th style="padding:4px">Samples</th><th style="padding:4px">Bandwidth</th>
<th style="padding:4px">Throughput</th><th style="padding:4px">Latency (p50/p90/p95/p99)</th>
<th style="padding:4px">Outstanding</th><th style="padding:4px">Stall Ratio</th>
<th style="padding:4px">Utilization</th><th style="padding:4px">BW Utilization</th></tr></thead>
<tbody id="ambaPerfPortBody"></tbody></table></div>
<div style="overflow-x:auto;margin-top:10px"><table id="ambaPerfPathTable" style="width:100%;border-collapse:collapse;font-size:12px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">Path</th><th style="padding:4px">Source -&gt; Dest</th><th style="padding:4px">Samples</th>
<th style="padding:4px">Bandwidth</th><th style="padding:4px">Throughput</th><th style="padding:4px">Latency (p50/p90/p95/p99)</th></tr></thead>
<tbody id="ambaPerfPathBody"></tbody></table></div>
<div class="note" id="ambaPerfRejectedNote" style="margin-top:8px"></div>
</div>

<div class="card" id="ambaPerfTrendCard"><h3>AMBA Performance Trend</h3>
<div class="note">Real <code>amba_performance_classification.compute_regression_delta()</code> /
<code>detect_anomaly()</code> results across a metric's own RECORDED PERIODS (GET
/api/amba-performance-trend, reading <code>.dv-harness/amba/performance_trend.json</code>): every
consecutive pair of recorded periods is compared through the real
<code>compute_regression_delta()</code> (IMPROVED/REGRESSED/UNCHANGED/INCONCLUSIVE, never a
fabricated percentage across incomparable units/windows), and every recorded period is checked
through the real <code>detect_anomaly()</code> against its own declared baseline. A metric with
fewer than 2 recorded periods honestly shows <b>INCONCLUSIVE</b> (a real delta needs two real
periods to compare); a metric with no recorded periods, or no trend file at all, honestly shows
<b>NOT_AVAILABLE</b> -- never a synthesized trend line. <b>Read-only</b>: this card runs no build,
simulation, or gate, and this harness owns no live simulator -- every period/value shown is
caller-supplied evidence, never estimated.</div>
<div id="ambaPerfTrendTiles" class="tiles" style="margin-top:8px"></div>
<div style="overflow-x:auto"><table id="ambaPerfTrendTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:6px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">Metric</th><th style="padding:4px">Periods</th><th style="padding:4px">Trend</th>
<th style="padding:4px">Regression Deltas</th><th style="padding:4px">Anomalies</th></tr></thead>
<tbody id="ambaPerfTrendBody"></tbody></table></div>
<div class="note" id="ambaPerfTrendRejectedNote" style="margin-top:8px"></div>
</div>

<div class="card" id="confidenceCalibrationCard"><h3>Confidence Calibration</h3>
<div class="note">Does a confidence tier's real track record (this project's own Memory records)
match the CONFIRMED &gt; HIGH &gt; MEDIUM &gt; LOW ordering this harness acts on? (GET
/api/confidence-calibration, reading <code>dv_harness.confidence_calibration.calibrate()</code>
live -- never a dashboard-local re-derivation of any tier's reliability/ordering finding).
<b>Read-only</b>: no memory record is written, no tier is promoted, and no gate is invoked -- a
MISCALIBRATED finding is a reporting signal for a human, never an approval in either direction.</div>
<div id="confidenceCalibrationTiles" class="tiles" style="margin-top:8px"></div>
<div class="ctrlrow" style="margin-top:6px"><button onclick="loadConfidenceCalibration()">Refresh</button></div>
<div style="overflow-x:auto"><table id="confidenceCalibrationTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:6px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">Tier</th><th style="padding:4px">Records</th><th style="padding:4px">Verified</th>
<th style="padding:4px">Rejected</th><th style="padding:4px">Determinate</th><th style="padding:4px">Reliability</th>
<th style="padding:4px">Calibratable</th><th style="padding:4px">Declared Floor</th></tr></thead>
<tbody id="confidenceCalibrationTableBody"></tbody></table></div>
<div class="note" id="confidenceCalibrationFindings" style="margin-top:8px"></div>
</div>

<div class="card" id="crossProjectMiningCard"><h3>Cross-Project Pattern Mining</h3>
<div class="note">VI-2: recurring root-cause/fix patterns across every project registered with this
host's <code>cross_project_mining.ProjectRegistry</code> (GET /api/cross-project-mining, reading
<code>dv_harness.cross_project_mining.production_status()</code> and
<code>mine_cross_project_patterns()</code> live -- never a dashboard-local re-derivation of a
signature, a project count, or a transferable-fix finding). A signature is reported as
cross-project only once at least 2 distinct registered projects recorded it -- fewer than that is
the honest <code>INSUFFICIENT_PROJECTS</code> answer about the sample, never a fabricated "no
patterns" finding. <b>Read-only</b>: no project is registered/unregistered, no memory record is
written, and nothing is promoted to Organizational Memory from this card -- a transferable-fix
finding is a question for a human review, never an approval in either direction.</div>
<div id="crossProjectMiningTiles" class="tiles" style="margin-top:8px"></div>
<div class="ctrlrow" style="margin-top:6px"><button onclick="loadCrossProjectMining()">Refresh</button></div>
<div style="overflow-x:auto"><table id="crossProjectMiningProjectsTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:6px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">Project</th><th style="padding:4px">Root</th><th style="padding:4px">Readable</th>
<th style="padding:4px">Failure Signatures</th><th style="padding:4px">Verified Fixes</th></tr></thead>
<tbody id="crossProjectMiningProjectsTableBody"></tbody></table></div>
<div style="overflow-x:auto;margin-top:8px"><table id="crossProjectMiningPatternsTable" style="width:100%;border-collapse:collapse;font-size:12px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">Signature</th><th style="padding:4px">Projects</th><th style="padding:4px">Resolved In</th>
<th style="padding:4px">Unresolved In</th><th style="padding:4px">Transferable Fix</th></tr></thead>
<tbody id="crossProjectMiningPatternsTableBody"></tbody></table></div>
<div class="note" id="crossProjectMiningDisclosure" style="margin-top:8px"></div>
</div>

<div class="card" id="verificationStrategyCard"><h3>Verification Strategy Optimizer</h3>
<div class="note">VI-4: which strategy (simulation/formal/PSS/emulation/FPGA prototype) this project's
own real coverage-closure/failure-density/protocol/topology signals indicate (GET
/api/verification-strategy, reading
<code>dv_harness.verification_strategy.execute_verb()</code> live -- never a dashboard-local
re-derivation of a signal or verdict). This harness can EXECUTE simulation only; every other
strategy is RECOMMEND_ONLY -- a recommendation for one is engineering advice for a human, never a
capability this harness can invoke. <b>Read-only</b>: no build, job, or approval is touched, and a
RECOMMEND_ONLY verdict is a reporting signal, never an approval in either direction.</div>
<div id="verificationStrategyTiles" class="tiles" style="margin-top:8px"></div>
<div class="ctrlrow" style="margin-top:6px"><button onclick="loadVerificationStrategy()">Refresh</button></div>
<div style="overflow-x:auto"><table id="verificationStrategyTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:6px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">Strategy</th><th style="padding:4px">Verdict</th><th style="padding:4px">Executability</th>
<th style="padding:4px">Basis</th><th style="padding:4px">Executable Next Action</th></tr></thead>
<tbody id="verificationStrategyTableBody"></tbody></table></div>
<div class="note" id="verificationStrategyDisclosure" style="margin-top:8px"></div>
</div>

<div class="card" id="generationReadinessCard"><h3>Generation Readiness Center</h3>
<div class="note">Section 211's real, auto-generated <code>Capability | Status | Existing Reuse |
Evidence | Gap | Priority | Action</code> table (GET /api/generation-readiness, reading
<code>dv_harness.generation_readiness.derive_generation_readiness()</code> -- never a
dashboard-local re-derivation of any cell). Every row's Status is the STRICT worse of two axes:
whether the generation mechanism the row names really exists and imports in this harness
(<b>Capability</b>, hover a row), and what this project's own real generation artifacts
(env.manifest.json's layers, the protocol capability registry, the subsystem environment
registry, the real SYS-1..40 cross-subsystem analysis) say about it -- a mechanism with no project
input reads UNKNOWN, never READY. Flow A is spec -&gt; subsystem UVM; Flow B is subsystem UVM
-&gt; system-level UVM. <b>Read-only</b>: this card runs no stage, invokes no gate script, starts
no build/regression/LSF job, and writes no governance state -- it is an input to a human's
generation decision, never an approval.</div>
<div id="generationReadinessTiles" class="tiles" style="margin-top:8px"></div>
<div class="ctrlrow" style="margin-top:6px"><label><input type="checkbox" id="generationReadinessDeep" checked onchange="loadGenerationReadiness()"> Deep analysis (SYS-1..SYS-30 cross-subsystem chain)</label>
  <button onclick="loadGenerationReadiness()">Refresh</button></div>
<div style="overflow-x:auto"><table id="generationReadinessTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:6px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">Capability</th><th style="padding:4px">Status</th><th style="padding:4px">Existing Reuse</th>
<th style="padding:4px">Evidence</th><th style="padding:4px">Gap</th><th style="padding:4px">Priority</th>
<th style="padding:4px">Action</th></tr></thead>
<tbody id="generationReadinessTableBody"></tbody></table></div>
<div class="note" id="generationReadinessNote" style="margin-top:8px"></div>
</div>

<div class="card" id="selfLearningReadinessCard"><h3>Self-Learning Readiness Matrix</h3>
<div class="note">Section 55's real, auto-generated 22-row matrix over this project's own
research/capability-evolution and five-tier-memory surfaces (GET /api/self-learning-readiness,
reading <code>dv_harness.self_learning_readiness.derive_self_learning_readiness()</code> -- never
a dashboard-local re-derivation of any cell). A different row set over different sources from the
Generation Readiness Center above -- none of that card's twenty rows are repeated here, and none
of these 22 rows are read through that card's own sources. <b>Read-only</b>: this card runs no
experiment, files no candidate, adds/retracts/confirms no memory record, and mints no approval --
it is an input to a human's review of this harness's own self-learning machinery, never an
approval.</div>
<div id="selfLearningReadinessTiles" class="tiles" style="margin-top:8px"></div>
<div class="ctrlrow" style="margin-top:6px"><button onclick="loadSelfLearningReadiness()">Refresh</button></div>
<div style="overflow-x:auto"><table id="selfLearningReadinessTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:6px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">Self-Learning Surface</th><th style="padding:4px">Status</th><th style="padding:4px">Evidence</th>
<th style="padding:4px">Gap</th><th style="padding:4px">Next-Best-Action</th></tr></thead>
<tbody id="selfLearningReadinessTableBody"></tbody></table></div>
<div class="note" id="selfLearningReadinessNote" style="margin-top:8px"></div>
</div>

<div class="card" id="smokeProofCard"><h3>Integration Proof Ladder</h3>
<div class="note">Section 206's real smoke-proof ladder (Build -&gt; Elaborate -&gt; Boot -&gt;
Shared-Resource -&gt; One-Subsystem -&gt; Two-Subsystem -&gt; End-to-End -&gt; WAVE -&gt;
Scoreboard -&gt; SYSTEM_READY), rung by rung (GET /api/system-smoke-proof, reading
<code>system_build_proof.SmokeProofReport.to_dict()</code> verbatim off
<code>.dv-harness/system_build_proof/smoke_proof_report.json</code> -- never a dashboard-local
re-derivation of any rung, and never a live re-run of the ladder). Produce the report with
<code>dv-harness system-smoke-proof --json &gt; .dv-harness/system_build_proof/smoke_proof_report.json</code>
for a project that has ALREADY run it. A <b>FAIL</b> halts the ladder -- rungs after it are
<code>NOT_YET_RUN</code>, a different fact from "checked and clean"; a <b>NOT_AVAILABLE</b>/<b>PENDING</b>
rung never rounds up to SYSTEM_READY. <b>Read-only</b>: this card runs no build/regression/LSF job and
authorizes nothing -- a SYSTEM_READY verdict here is the precondition for large LSF system
regression, never an approval to launch one.</div>
<div id="smokeProofTiles" class="tiles" style="margin-top:8px"></div>
<div class="ctrlrow" style="margin-top:6px"><button onclick="loadSmokeProof()">Refresh</button></div>
<div style="overflow-x:auto"><table id="smokeProofTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:6px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">#</th><th style="padding:4px">Rung</th><th style="padding:4px">Status</th>
<th style="padding:4px">Reason</th></tr></thead>
<tbody id="smokeProofTableBody"></tbody></table></div>
<div class="note" id="smokeProofNote" style="margin-top:8px"></div>
</div>

<div class="card" id="designKnowledgeCard"><h3>Design Knowledge Explorer</h3>
<div class="note">Real cross-source <code>design_knowledge_correlation.correlate()</code> report (GET
/api/design-knowledge, computed live off <code>.dv-harness/design_knowledge/sources.json</code> +
optional <code>expected_facts.json</code>) -- the Design Knowledge Graph's own SOURCE/FACT nodes
with per-fact provenance, and every real <b>CONFLICT</b> / <b>GAP</b> /
<b>DOCUMENTED_VS_IMPLEMENTED</b> finding that module's own <code>correlate()</code> detected. That
module is deliberately generic -- it imports nothing from <code>dv_harness</code> and discovers no
project fact itself; a caller/extraction step assembles the real <code>sources</code> list from a
producer's own output (spec / RTL / vPlan / ...) and writes it to <code>sources.json</code>. No
<code>sources.json</code> on disk yet shows an honest empty state naming the file this card looked
for, never a fabricated graph. <b>Read-only</b>: this card runs no build, simulation, or gate -- it
only renders what <code>correlate()</code> itself computed from real, already-extracted facts.</div>
<div id="designKnowledgeTiles" class="tiles" style="margin-top:8px"></div>
<div class="ctrlrow" style="margin-top:6px"><button onclick="loadDesignKnowledge()">Refresh</button></div>
<div class="note" id="designKnowledgeEmptyNote" style="margin-top:8px"></div>
<div class="note" style="margin-top:12px"><b>Sources</b></div>
<div style="overflow-x:auto"><table id="designKnowledgeSourcesTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:4px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">Source ID</th><th style="padding:4px">Kind</th><th style="padding:4px">Role</th>
<th style="padding:4px">Fact Count</th></tr></thead>
<tbody id="designKnowledgeSourcesBody"></tbody></table></div>
<div class="note" style="margin-top:12px"><b>Facts</b> (click a row for per-source provenance)</div>
<div style="overflow-x:auto"><table id="designKnowledgeFactsTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:4px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">Fact Key</th><th style="padding:4px">Type(s)</th><th style="padding:4px">Consensus</th>
<th style="padding:4px">Distinct Values</th><th style="padding:4px">Assertions</th></tr></thead>
<tbody id="designKnowledgeFactsBody"></tbody></table></div>
<div class="note" id="designKnowledgeFactDetail" style="margin-top:6px"></div>
<div class="note" style="margin-top:12px"><b>Findings</b> (CONFLICT / GAP / DOCUMENTED_VS_IMPLEMENTED)</div>
<div style="overflow-x:auto"><table id="designKnowledgeFindingsTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:4px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">Type</th><th style="padding:4px">Fact Key</th><th style="padding:4px">Reason</th></tr></thead>
<tbody id="designKnowledgeFindingsBody"></tbody></table></div>
<div class="note" id="designKnowledgeErrorNote" style="margin-top:6px"></div>
</div>

<div class="card" id="requirementVplanCard"><h3>Requirement / vPlan Center</h3>
<div class="note">Real <code>requirement_contract.analyze_requirement_contract_set()</code> and
<code>vplan_artifact.analyze_vplan_completeness()</code> reports (GET /api/requirement-vplan-center,
computed live off <code>.dv-harness/requirement_vplan/requirements.json</code> and
<code>.../vplan.json</code>) -- every requirement's own five-value status
(COMPLETE/PARTIAL/AMBIGUOUS/CONTRADICTORY/UNKNOWN), the vPlan's real
<b>nine-dimension</b> completeness matrix (never collapsed to one score), and every real gap from
the fifteen-value gap taxonomy with its Next-Best-Action. Neither module discovers a project's own
records itself; a real upstream extraction step writes the two files this card reads. Neither file on
disk yet shows an honest empty state naming the two files this card looked for, never a fabricated
table. <b>Read-only</b>: this card runs no build, simulation, or gate -- it only renders what the two
real analyzers themselves computed.</div>
<div id="requirementVplanTiles" class="tiles" style="margin-top:8px"></div>
<div class="ctrlrow" style="margin-top:6px"><button onclick="loadRequirementVplan()">Refresh</button></div>
<div class="note" id="requirementVplanEmptyNote" style="margin-top:8px"></div>
<div class="note" id="requirementVplanErrorNote" style="margin-top:6px"></div>
<div class="note" style="margin-top:12px"><b>Requirements</b></div>
<div style="overflow-x:auto"><table id="requirementTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:4px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">Requirement ID</th><th style="padding:4px">Declared Status</th>
<th style="padding:4px">Findings</th></tr></thead>
<tbody id="requirementBody"></tbody></table></div>
<div style="overflow-x:auto"><table id="requirementFindingsTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:8px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">Severity</th><th style="padding:4px">Code</th><th style="padding:4px">Requirement</th>
<th style="padding:4px">Detail</th></tr></thead>
<tbody id="requirementFindingsBody"></tbody></table></div>
<div class="note" style="margin-top:12px"><b>vPlan Completeness Matrix</b> (nine dimensions, never
averaged)</div>
<div style="overflow-x:auto"><table id="vplanDimensionsTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:4px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">Dimension</th><th style="padding:4px">Status</th><th style="padding:4px">Applicable</th>
<th style="padding:4px">Gaps</th><th style="padding:4px">Reason</th></tr></thead>
<tbody id="vplanDimensionsBody"></tbody></table></div>
<div class="note" style="margin-top:12px"><b>vPlan Gaps + Next-Best-Action</b> (fifteen-value gap
taxonomy)</div>
<div style="overflow-x:auto"><table id="vplanGapsTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:4px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">Gap</th><th style="padding:4px">Severity</th><th style="padding:4px">Row</th>
<th style="padding:4px">Detail</th></tr></thead>
<tbody id="vplanGapsBody"></tbody></table></div>
<div class="note" id="vplanNextActionsNote" style="margin-top:8px"></div>
</div>

<div class="card" id="questionQueueCard"><h3>Question Queue</h3>
<div class="note">Real <code>question_queue.py</code> 3-tier ask-a-human state (GET /api/question-queue) --
every pending (OPEN/ASSUMED) question with its own real 9-field escalation package
(<code>build_escalation_package()</code>: category, context, options, recommended option,
default-if-unanswered, owner, urgency -- hover a row), every recorded decision (Tier-2
auto-assumption or a real human answer), and the real Part-B tracking metrics
(<code>self_resolve_rate</code>/<code>blocking_questions_per_week</code>/<code>repeat_question_rate</code>/
<code>assumption_overturned_rate</code>). Answering or revoking a decision below goes out through the
existing <code>POST /api/control</code> dispatch (<code>QUESTION_ANSWER</code>/<code>QUESTION_REVOKE</code>),
calling <code>QuestionQueueStore.answer_question()</code>/<code>revoke_decision()</code> verbatim -- the
SAME writes <code>dv-harness question-queue answer</code>/<code>revoke</code> already perform.
<b>Read-only display</b>: this card never files a question, never re-derives a tier classification, and
never computes a digest/metric itself.</div>
<div id="questionQueueTiles" class="tiles" style="margin-top:8px"></div>
<div class="ctrlrow" style="margin-top:6px"><button onclick="loadQuestionQueue()">Refresh</button></div>
<div class="note" id="questionQueueErrorNote" style="margin-top:6px"></div>
<div class="note" style="margin-top:12px"><b>Pending Questions</b> (OPEN = Tier-3 blocking; ASSUMED =
Tier-2 auto-assumption, provisional until a human confirms or overturns it)</div>
<div style="overflow-x:auto"><table id="questionQueueTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:4px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">Q-ID</th><th style="padding:4px">Domain</th><th style="padding:4px">Owner</th>
<th style="padding:4px">Status</th><th style="padding:4px">Blocking</th><th style="padding:4px">Question</th>
<th style="padding:4px">Options</th><th style="padding:4px">Recommendation</th>
<th style="padding:4px">Answer</th></tr></thead>
<tbody id="questionQueueTableBody"></tbody></table></div>
<div class="ctrlrow" style="margin-top:8px">
<input id="qqAnswer" placeholder="answer" style="width:10em">
<input id="qqBasis" placeholder="basis" style="width:10em">
<input id="qqDecidedBy" placeholder="decided by" style="width:8em">
</div>
<div class="note" style="margin-top:12px"><b>Recorded Decisions</b> (most recent 50; revoke re-opens the
question_key for the next ask -- the sanctioned undo, per <code>QuestionQueueStore.revoke_decision()</code>)</div>
<div style="overflow-x:auto"><table id="questionQueueDecisionsTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:4px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">Q-ID</th><th style="padding:4px">question_key</th><th style="padding:4px">Status</th>
<th style="padding:4px">Answer</th><th style="padding:4px">Decided By</th><th style="padding:4px">Answered At</th>
<th style="padding:4px">Revoke</th></tr></thead>
<tbody id="questionQueueDecisionsBody"></tbody></table></div>
<div class="ctrlrow" style="margin-top:8px">
<input id="qqRevokeReason" placeholder="revoke reason" style="width:12em">
<input id="qqRevokedBy" placeholder="revoked by" style="width:8em">
</div>
<pre id="questionQueueResult" style="margin-top:8px"></pre>
</div>

<div class="card" id="evidenceIntegritySignoffBlockersCard"><h3>Evidence Integrity + Signoff Blocker Center</h3>
<div class="note">Real <code>evidence_integrity_states.classify_project_evidence_integrity()</code> and
<code>signoff_blocker_list.derive_signoff_blockers()</code> reports (GET
/api/evidence-integrity-signoff-blockers, computed live off this project's own real
<code>evidence.duckdb</code>, signoff freeze store, waiver ledger, and functional-coverage
evidence) -- every recorded golden-scenario capsule's and signoff freeze's own
<b>VALID/STALE/SUPERSEDED/CONTRADICTED/CORRUPT/UNKNOWN</b> integrity state, and the real
twelve-dimension, worst-wins signoff-blocker rollup (<code>CLOSED</code>/<code>NOT_CLOSED</code>/
<code>INCOMPLETE_EVIDENCE</code>) over the nine <code>BLOCKER_CATEGORIES</code> this codebase has
no other real source for plus the three natively-resolved dimensions
(functional_coverage/waiver_status/evidence_integrity). A project recording no evidence at all
shows an honest <b>NOT_AVAILABLE</b>/<b>INCOMPLETE_EVIDENCE</b>, never a fabricated CLOSED.
<b>Read-only</b>: this card runs no build, simulation, gate, or approval -- it decides no
arbitration and revokes no waiver; a listed blocker is an input to a human's signoff review,
never a substitute for one.</div>
<div id="eisTiles" class="tiles" style="margin-top:8px"></div>
<div class="ctrlrow" style="margin-top:6px"><button onclick="loadEvidenceIntegritySignoffBlockers()">Refresh</button></div>
<div class="note" id="eisErrorNote" style="margin-top:6px"></div>
<div class="note" style="margin-top:12px"><b>Evidence Integrity Records</b> (recorded golden-scenario
capsules + signoff freezes)</div>
<div style="overflow-x:auto"><table id="eisIntegrityTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:4px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">Kind</th><th style="padding:4px">ID</th><th style="padding:4px">State</th>
<th style="padding:4px">Reason(s)</th></tr></thead>
<tbody id="eisIntegrityBody"></tbody></table></div>
<div class="note" style="margin-top:12px"><b>Signoff Dimensions</b> (twelve dimensions, worst-wins --
never averaged)</div>
<div style="overflow-x:auto"><table id="eisDimensionsTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:4px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">Dimension</th><th style="padding:4px">Core-9</th><th style="padding:4px">Status</th>
<th style="padding:4px">Reason(s)</th></tr></thead>
<tbody id="eisDimensionsBody"></tbody></table></div>
<div class="note" id="eisSignoffNote" style="margin-top:8px"></div>
</div>

<div class="card" id="testSuiteCenterCard"><h3>Test Suite Center</h3>
<div class="note">Real <code>test_suite_lifecycle.derive_test_suite_lifecycle()</code> report
(GET /api/test-suite-center, computed live off this project's own real
<code>.dv-harness/evidence/evidence.duckdb</code>) -- every test pattern's own lifecycle state,
derived ONLY from real <code>evidence_db.py</code> job/regression records and
<code>golden_scenario.py</code> capsules: <b>GENERATED</b> through <b>CLOSURE_PROVEN</b> (the
seven-state core progression), never fabricated for a pattern with no real evidence
(<b>UNKNOWN</b>). The three relationship tags (<b>SEMANTIC_DUPLICATE</b>/<b>SUBSUMED</b>/
<b>SUPERSET</b>) have no real producer in this codebase and are never derived here either -- they
are shown only when a caller-declared, evidence-cited fact is on disk at
<code>.dv-harness/test_suite/relationships.json</code>. No evidence database on disk yet shows an
honest empty state, never a fabricated table. <b>Read-only</b>: this card runs no build,
simulation, or gate.</div>
<div id="testSuiteCenterTiles" class="tiles" style="margin-top:8px"></div>
<div class="ctrlrow" style="margin-top:6px"><button onclick="loadTestSuiteCenter()">Refresh</button></div>
<div class="note" id="testSuiteCenterEmptyNote" style="margin-top:8px"></div>
<div class="note" id="testSuiteCenterErrorNote" style="margin-top:6px"></div>
<div style="overflow-x:auto"><table id="testSuitePatternTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:4px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">Pattern</th><th style="padding:4px">Lifecycle State</th>
<th style="padding:4px">Jobs</th><th style="padding:4px">Latest LSF Status</th>
<th style="padding:4px">Regression Verdict</th><th style="padding:4px">Golden Capsules</th>
<th style="padding:4px">Relationships</th></tr></thead>
<tbody id="testSuitePatternBody"></tbody></table></div>
</div>

<div class="card" id="subsystemSystemVerificationCard"><h3>Subsystem Verification Center + System Integration Center</h3>
<div class="note">Real <code>subsystem_contract.assemble_subsystem_contract()</code> and
<code>system_verification_contract.assemble_system_verification_contract()</code> records, plus
<code>ip_ownership_conflict.analyze_ip_ownership_conflict()</code> and <code>system_resource_inventory.
real_cross_subsystem_findings()</code> compatibility findings (GET /api/subsystem-system-verification),
computed live off this project's own real registered-subsystem set -- never a dashboard-local
re-derivation of any field. An optional <code>.dv-harness/subsystem_system_verification/inputs.json</code>
overlay supplies the facts this repo has no fixed producer for yet (per-subsystem
<code>legacy_bfm_declarations</code>/<code>connectivity_rows</code>, a real
<code>system_topology_analysis</code>/<code>system_command_plan</code>-shaped document); absent that
overlay those specific sections honestly show NOT_APPLICABLE/NOT_AVAILABLE, never a fabricated pass.
<b>Read-only</b>: all four underlying modules are read-only by their own documented contract -- this
card runs no stage, invokes no gate script, and mints no approval; a real ownership/resource conflict
is reported with SYS-12's preferred-resolution text for a human, never resolved here.</div>
<div id="ssvTiles" class="tiles" style="margin-top:8px"></div>
<div class="ctrlrow" style="margin-top:6px"><button onclick="loadSubsystemSystemVerification()">Refresh</button></div>
<div class="note" id="ssvErrorNote" style="margin-top:6px"></div>
<div class="note" style="margin-top:12px"><b>Subsystem Contracts</b></div>
<div style="overflow-x:auto"><table id="ssvSubsystemTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:4px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">Subsystem</th><th style="padding:4px">Completeness</th>
<th style="padding:4px">Spec/DUT/TB</th><th style="padding:4px">Protocols</th>
<th style="padding:4px">Regression</th><th style="padding:4px">Signoff Stage</th>
<th style="padding:4px">Evidence</th><th style="padding:4px">Waivers</th>
<th style="padding:4px">IP Ownership</th></tr></thead>
<tbody id="ssvSubsystemBody"></tbody></table></div>
<div class="note" style="margin-top:12px"><b>System Verification Contract</b></div>
<div class="note" id="ssvSystemNote" style="margin-top:4px"></div>
<div style="overflow-x:auto"><table id="ssvUnknownsTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:4px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">Field</th><th style="padding:4px">Reason</th></tr></thead>
<tbody id="ssvUnknownsBody"></tbody></table></div>
<div class="note" id="ssvErrorsNote" style="margin-top:8px"></div>
</div>

<div class="card" id="verificationArchitectureCard"><h3>Verification Architecture View</h3>
<div class="note">Real <code>verification_architecture.assemble_verification_architecture()</code>
document (GET /api/verification-architecture, computed live off
<code>.dv-harness/verification_architecture/inputs.json</code>) -- the 5 required matrices
(<b>VIP Bind</b>, <b>Interface-to-Verification</b>, <b>Function-to-Checker</b>,
<b>Assertion Placement</b>, <b>Scoreboard Architecture</b>) rendered exactly as that module's own
<code>render_*_matrix()</code> functions produce them, plus its two real comparators
(<code>detect_placement_conflicts()</code>/<code>detect_intra_subsystem_duplicates()</code>). That
module discovers no project fact itself; a real upstream assembly step writes the one file this card
reads. No file on disk yet shows an honest empty state naming it, never a fabricated matrix.
<b>Read-only</b>: this card runs no build, simulation, bind, or gate -- it only renders what the real
module itself computed, schema-validated against <code>verification_architecture.schema.json</code>
before being served.</div>
<div id="verificationArchitectureTiles" class="tiles" style="margin-top:8px"></div>
<div class="ctrlrow" style="margin-top:6px"><button onclick="loadVerificationArchitecture()">Refresh</button></div>
<div class="note" id="verificationArchitectureEmptyNote" style="margin-top:8px"></div>
<div class="note" id="verificationArchitectureErrorNote" style="margin-top:6px"></div>
<div class="note" style="margin-top:12px"><b>VIP Bind Matrix</b></div>
<pre id="vaVipBindMatrix" style="white-space:pre-wrap;font-size:12px;background:#f7f9fc;border:1px solid #e3e9f2;border-radius:6px;padding:8px;margin-top:4px"></pre>
<div class="note" style="margin-top:12px"><b>Interface-to-Verification Matrix</b></div>
<pre id="vaInterfaceMatrix" style="white-space:pre-wrap;font-size:12px;background:#f7f9fc;border:1px solid #e3e9f2;border-radius:6px;padding:8px;margin-top:4px"></pre>
<div class="note" style="margin-top:12px"><b>Function-to-Checker Matrix</b></div>
<pre id="vaCheckerMatrix" style="white-space:pre-wrap;font-size:12px;background:#f7f9fc;border:1px solid #e3e9f2;border-radius:6px;padding:8px;margin-top:4px"></pre>
<div class="note" style="margin-top:12px"><b>Assertion Placement Matrix</b></div>
<pre id="vaAssertionMatrix" style="white-space:pre-wrap;font-size:12px;background:#f7f9fc;border:1px solid #e3e9f2;border-radius:6px;padding:8px;margin-top:4px"></pre>
<div class="note" style="margin-top:12px"><b>Scoreboard Architecture Matrix</b></div>
<pre id="vaScoreboardMatrix" style="white-space:pre-wrap;font-size:12px;background:#f7f9fc;border:1px solid #e3e9f2;border-radius:6px;padding:8px;margin-top:4px"></pre>
<div class="note" style="margin-top:12px"><b>Placement Conflicts</b></div>
<div style="overflow-x:auto"><table id="vaConflictsTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:4px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">Kind</th><th style="padding:4px">Severity</th><th style="padding:4px">Summary</th></tr></thead>
<tbody id="vaConflictsBody"></tbody></table></div>
<div class="note" style="margin-top:12px"><b>Intra-Subsystem Duplicates</b></div>
<div style="overflow-x:auto"><table id="vaDuplicatesTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:4px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">Kind</th><th style="padding:4px">Severity</th><th style="padding:4px">Summary</th></tr></thead>
<tbody id="vaDuplicatesBody"></tbody></table></div>
</div>

<div class="card" id="systemTransactionE2EScoreboardCard"><h3>System Transaction View + End-to-End Scoreboard</h3>
<div class="note">Real <code>amba_transaction_ir.py</code>'s 22-field transaction shape, composed
cross-subsystem via <code>system_transaction_ir.build_system_transaction_ir()</code>; real
<code>transaction_correlation_ir.py</code> correlated/reconstructed logical AXI transaction records
(<code>correlate_responses()</code> / <code>associate_data_beats()</code> /
<code>reconstruct_logical_transactions()</code>); and real system-scope scoreboard-placement facts for a
composed system via <code>system_scoreboard_ir.build_system_scoreboard_ir()</code> (GET
/api/system-transaction-e2e-scoreboard, computed live off
<code>.dv-harness/system_transaction_e2e_scoreboard/inputs.json</code>). None of the three modules
discovers a project's own facts itself; a real upstream step writes the one overlay file this card reads,
and each of the three sections is built independently -- one section's own error never hides the other
two. No file on disk yet shows an honest empty state naming it, never a fabricated table. <b>Read-only</b>:
this card runs no build, simulation, or gate -- it only renders what the three real modules themselves
computed, and never merges/arbitrates a genuine cross-fabric or cross-scoreboard disagreement.</div>
<div id="steTiles" class="tiles" style="margin-top:8px"></div>
<div class="ctrlrow" style="margin-top:6px"><button onclick="loadSystemTransactionE2EScoreboard()">Refresh</button></div>
<div class="note" id="steEmptyNote" style="margin-top:8px"></div>
<div class="note" id="steErrorNote" style="margin-top:6px"></div>
<div class="note" style="margin-top:12px"><b>System Transaction (amba_transaction_ir composed cross-subsystem)</b></div>
<pre id="steSystemTransactionPre" style="white-space:pre-wrap;font-size:12px;background:#f7f9fc;border:1px solid #e3e9f2;border-radius:6px;padding:8px;margin-top:4px"></pre>
<div class="note" style="margin-top:12px"><b>Correlated / Reconstructed Logical Transactions</b></div>
<pre id="steTransactionCorrelationPre" style="white-space:pre-wrap;font-size:12px;background:#f7f9fc;border:1px solid #e3e9f2;border-radius:6px;padding:8px;margin-top:4px"></pre>
<div class="note" style="margin-top:12px"><b>System-Scope Scoreboard Placement (End-to-End Coverage)</b></div>
<pre id="steSystemScoreboardPre" style="white-space:pre-wrap;font-size:12px;background:#f7f9fc;border:1px solid #e3e9f2;border-radius:6px;padding:8px;margin-top:4px"></pre>
</div>

<div class="card" id="vipEnvironmentBuilderCard"><h3>VIP/UVM Environment Builder</h3>
<div class="note">Real <code>protocol_capability.py</code> per-protocol <code>capability_status</code>
(same real <code>qualification/protocol_capability_registry.json</code> the Protocols card above
reads) shown alongside <code>vip_api_card.validate_vip_api_usage()</code>'s real
<b>PROVEN</b>/<b>BLOCKED</b>/<b>UNPROVABLE</b> citation report for a generated environment (GET
/api/vip-environment-builder, computed live off <code>.dv-harness/vip_evidence/inputs.json</code>).
A <b>BLOCKED</b> citation is a VIP API call the real <code>vip_symbol_index</code> proves does not
exist -- never generated, per spec section 187's "If API cannot be proven: UNKNOWN / BLOCKED".
Neither module discovers a project's own generated sources itself; a real upstream step writes the
one file this card reads. No file on disk yet shows an honest empty state naming it, never a
fabricated card. <b>Read-only</b>: this card runs no build, VIP indexing, or generation -- it only
renders what the two real modules themselves computed.</div>
<div class="note" style="margin-top:8px"><b>Protocol Capability</b></div>
<div id="vipEnvBuilderProtocolTiles" class="tiles" style="margin-top:4px"></div>
<div class="ctrlrow" style="margin-top:10px"><button onclick="loadVipEnvironmentBuilder()">Refresh</button></div>
<div class="note" id="vipEnvBuilderEmptyNote" style="margin-top:8px"></div>
<div class="note" id="vipEnvBuilderErrorNote" style="margin-top:6px"></div>
<div class="note" style="margin-top:12px"><b>VIP API Evidence</b></div>
<div id="vipEnvBuilderTiles" class="tiles" style="margin-top:4px"></div>
<div class="note" style="margin-top:10px"><b>BLOCKED</b> -- cannot be proven, must not be generated</div>
<div style="overflow-x:auto"><table id="vipEnvBuilderBlockedTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:4px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">Citation</th><th style="padding:4px">Reason</th><th style="padding:4px">Cited At</th></tr></thead>
<tbody id="vipEnvBuilderBlockedBody"></tbody></table></div>
<div class="note" style="margin-top:10px"><b>UNPROVABLE</b> -- UNKNOWN per spec 187</div>
<div style="overflow-x:auto"><table id="vipEnvBuilderUnprovableTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:4px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">Citation</th><th style="padding:4px">Reason</th><th style="padding:4px">Cited At</th></tr></thead>
<tbody id="vipEnvBuilderUnprovableBody"></tbody></table></div>
<div class="note" style="margin-top:10px"><b>PROVEN</b> -- VIPApiCard -&gt; real VIP source location</div>
<div style="overflow-x:auto"><table id="vipEnvBuilderProvenTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:4px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">Citation</th><th style="padding:4px">Resolved Location</th><th style="padding:4px">Declared By</th></tr></thead>
<tbody id="vipEnvBuilderProvenBody"></tbody></table></div>
</div>

<div class="card" id="orphanedForkDetectionCard"><h3>Orphaned/Leaked-Fork Detection</h3>
<div class="note">Real <code>orphaned_fork_detection.analyze_pattern_directory()</code> report (GET
/api/orphaned-fork-detection, computed live off
<code>.dv-harness/orphaned_fork_detection/inputs.json</code>) -- for every <code>branch_b*</code>
region in every real command.txt/pattern file scanned, whether every non-blocking VIP-sequence
DISPATCH has a real, paired explicit WAIT before that branch reports a result, per
<code>pattern-architecture</code> SKILL.md section 3.5. This module discovers no project fact
itself; a caller declares which real <code>pattern_dir</code> to scan. No
<code>inputs.json</code> on disk yet shows an honest empty state naming the file this card looked
for, never a fabricated pattern_dir. <b>Read-only</b>: this card runs no build or generation -- it
only renders what <code>analyze_pattern_directory()</code> itself found in real source text.</div>
<div id="orphanedForkTiles" class="tiles" style="margin-top:8px"></div>
<div class="ctrlrow" style="margin-top:6px"><button onclick="loadOrphanedForkDetection()">Refresh</button></div>
<div class="note" id="orphanedForkEmptyNote" style="margin-top:8px"></div>
<div class="note" id="orphanedForkErrorNote" style="margin-top:6px"></div>
<div style="overflow-x:auto"><table id="orphanedForkFilesTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:6px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">File</th><th style="padding:4px">Status</th><th style="padding:4px">Reason</th>
<th style="padding:4px">Regions</th></tr></thead>
<tbody id="orphanedForkFilesBody"></tbody></table></div>
</div>

<div class="card" id="multiVipCooperationCard"><h3>Multi-VIP Cooperation Architecting</h3>
<div class="note">Real <code>multi_vip_cooperation_architecting.build_multi_vip_cooperation()</code>
report (GET /api/multi-vip-cooperation, computed live off
<code>.dv-harness/multi_vip_cooperation/inputs.json</code>) -- for every DUT+PHY topology whose
declared interfaces share a real coupling fact (e.g. one physical PHY instance backing two logical
interfaces, a dual-role port), whether that pairing genuinely needs two cooperating VIP instances,
and if so, whether the shared virtual-sequencer composition and interface-readiness sequencing are
fully architected yet. Every fact (interfaces, coupling, sequencing) must be caller-declared -- this
module has no project-discovery path of its own. No <code>inputs.json</code> on disk yet shows an
honest empty state naming the file this card looked for, never a fabricated cooperation record.
<b>Read-only</b>: this card runs no build or generation, and picks no winner between two active
drivers -- it only renders what <code>build_multi_vip_cooperation()</code> itself computed from
real, caller-declared evidence.</div>
<div id="multiVipCoopTiles" class="tiles" style="margin-top:8px"></div>
<div class="ctrlrow" style="margin-top:6px"><button onclick="loadMultiVipCooperation()">Refresh</button></div>
<div class="note" id="multiVipCoopEmptyNote" style="margin-top:8px"></div>
<div class="note" id="multiVipCoopErrorNote" style="margin-top:6px"></div>
<div style="overflow-x:auto"><table id="multiVipCoopRelTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:6px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">Interface A</th><th style="padding:4px">Interface B</th>
<th style="padding:4px">Cooperation</th><th style="padding:4px">Architecture</th>
<th style="padding:4px">Sequencing</th><th style="padding:4px">Vseqr Composition</th></tr></thead>
<tbody id="multiVipCoopRelBody"></tbody></table></div>
</div>

<div class="card" id="dutErrataCorrelationCard"><h3>DUT Errata/Known-Issues Correlation</h3>
<div class="note">Real <code>dut_errata_correlation.analyze_errata()</code> report (GET
/api/dut-errata-correlation, computed live off
<code>.dv-harness/dut_errata_correlation/inputs.json</code>'s declared <code>source_path</code>
plus this project's own real <code>env.manifest.json</code>, auto-resolved) -- every real erratum
this module structurally extracted from the declared errata/known-issues document, correlated
against real RTL/register evidence: <b>RTL_LOCATED</b> (a real exact match), <b>RTL_PARTIALLY_
LOCATED</b> (an unproven substring match), <b>RTL_NOT_LOCATED</b> (searched, not found -- a real
negative), <b>NO_AFFECTED_COMPONENT_CITED</b>, or the honest <b>NOT_AVAILABLE</b> when no
manifest was available to check against -- never collapsed into RTL_NOT_LOCATED. No
<code>source_path</code> declared reports the honest top-level NOT_AVAILABLE without ever
attempting to open anything, never a fabricated erratum list. <b>Read-only</b>: this card runs no
build or generation -- it only renders what <code>analyze_errata()</code> itself extracted and
correlated from real evidence.</div>
<div id="dutErrataTiles" class="tiles" style="margin-top:8px"></div>
<div class="ctrlrow" style="margin-top:6px"><button onclick="loadDutErrataCorrelation()">Refresh</button></div>
<div class="note" id="dutErrataErrorNote" style="margin-top:6px"></div>
<div style="overflow-x:auto"><table id="dutErrataTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:6px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">Erratum ID</th><th style="padding:4px">Title</th>
<th style="padding:4px">Correlation</th><th style="padding:4px">Affected Components</th></tr></thead>
<tbody id="dutErrataBody"></tbody></table></div>
</div>

<div class="card" id="researchCard"><h3>Research / Capability Evolution</h3>
<div class="note">Real <code>CapabilityEvolutionCandidate</code> records -- the harness reasoning about
changes to ITSELF (GET /api/research, reading <code>capability_evolution.read_candidates()</code> off
the one Blackboard topic <code>capability_evolution_candidates</code>). Every column is read from
<code>dv_harness/capability_evolution.py</code>: the KEEP/ENHANCE/ADD/EXPERIMENT/REJECT recommendation
and the EXISTS/PARTIAL_MATCH/MISSING overlap are that module's own
<code>decide_recommendation()</code> output (derived from the candidate's six repository searches,
never accepted from a caller), the promotion state is its section-70 state machine, and
<b>Legal next</b> is <code>LEGAL_TRANSITIONS</code> itself -- so a button the state machine would
refuse is never offered as if it worked. No candidate filed yet shows an honest empty state, never a
fabricated proposal.
<br><b>Approve / Reject / Hold are the real Human Approval Gate</b>, posted through the SAME
<code>POST /api/control</code> dispatch every other Human Control Plane verb on this page uses:
<b>Approve</b> writes the real <code>ControlPlane</code> approval for stage
<code>RESEARCH_CAPABILITY_EVOLUTION</code> (byte-identical to
<code>dv-harness approve RESEARCH_CAPABILITY_EVOLUTION</code>) and then runs the real
<code>transition()</code>, which re-reads that approval off disk through
<code>assert_human_approval()</code> and copies it into the candidate's own
<code>status_history</code>; <b>Reject</b> is <code>transition(..., "REJECTED")</code>;
<b>Hold</b> withdraws the standing approval (archived as <code>WITHDRAWN_BY_HUMAN_HOLD</code>, never
deleted), which really blocks two things: no candidate can transition into HUMAN_APPROVED, and
<code>assert_no_production_write_authorized()</code> then refuses a Stage-3 production write even on
a candidate that already reached HUMAN_APPROVED. There is no second approval store anywhere.
<br><b>Two disclosed limits.</b> (1) Hold is STAGE-scoped, not candidate-scoped -- the gate
<code>ControlPlane</code> owns is keyed on the stage string and <code>PROMOTION_STATES</code> has no
HOLD state, so a hold withholds authorization for every candidate at once and the candidate it names
is recorded as the reason. (2) Approving here is Stage 3 authorization only: it authorizes a human to
implement the change, it does not implement anything, and reaching <code>main</code>/<code>master</code>
still goes through the PR-only governance gate.</div>
<div id="researchTiles" class="tiles" style="margin-top:8px"></div>
<div class="note" id="researchApprovalNote" style="margin-top:8px"></div>
<div class="ctrlrow" style="margin-top:6px"><label>Note / reason (required)
  <input id="researchNote" size="34" placeholder="what you are approving / rejecting / holding"></label>
  <label>Reviewer <input id="researchReviewer" size="12" placeholder="reviewer id"></label>
  <label>Confidence <select id="researchConfidence"><option>HIGH</option><option>MEDIUM</option><option>LOW</option></select></label>
  <button class="secondary" onclick="doResearchAction('RESEARCH_HOLD',null)">Hold Gate (withdraw standing approval)</button></div>
<div style="overflow-x:auto"><table id="researchTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:6px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">Candidate</th><th style="padding:4px">Affected Capability</th>
<th style="padding:4px">Recommendation</th><th style="padding:4px">Overlap</th>
<th style="padding:4px">Promotion State</th><th style="padding:4px">Confidence</th>
<th style="padding:4px">Legal next</th><th style="padding:4px">Actions</th></tr></thead>
<tbody id="researchTableBody"></tbody></table></div>
<div id="researchResult"></div>
</div>

<div class="card" id="blackboardEvidenceCard"><h3>Blackboard Evidence</h3>
<div class="note" id="blackboardEvidenceNote"></div>
<div class="note" style="margin-top:6px">Current blackboard topics (real, from <code>.dv-harness/blackboard/</code>): <span id="blackboardTopicsList"></span></div>
</div>
<div class="card" id="hypothesisReviewCard"><h3>Hypothesis &amp; Review</h3>
<div class="note">Dedicated entry point for the failure-hypothesis and DV sign-off review data already
computed below -- see <a href="#attributionCard">Attribution</a> for the recomputed
<code>failure_attribution</code> verdict (HYPOTHESIS) and <a href="#dvReviewCard">DV Review</a> for
pending co-sign fields (REVIEW). No new logic here, just a labeled pointer to both.</div>
<div id="hyprevtiles" class="tiles" style="margin-top:8px"></div>
<div class="note" style="margin-top:10px">Qualified Conclusion (RE_AUDIT's real
<code>qualified_conclusion</code> Blackboard topic -- composes the stage's gate verdict with an
independently-recomputed confidence level, never the agent's own self-reported confidence field):
an unqualified result is labeled <b>AI Opinion</b> -- a bare, not-yet-qualified conclusion to
investigate further, not a verified finding.</div>
<div id="qualtiles" class="tiles" style="margin-top:8px"></div>
</div>
<div class="card" id="attributionCard"><h3>Attribution</h3>
<div class="note">Recomputed the same way the FAILURE_RECOVERY <code>failure_attribution</code> gate itself decides
PASS/FAIL -- from <code>boundary_trace</code>'s first expected/observed mismatch, never from the agent's own
self-reported classification field (that field is never checked by the gate either). Shows "-" until
FAILURE_RECOVERY has actually run once; stays visible after the run advances past that stage.</div>
<div id="attrtiles" class="tiles"></div></div>
<div class="card"><h3>Project Health</h3>
<div class="note">Everything below is already computed elsewhere on this page (Status/Findings/DV Review/Control
Plane) -- this card just puts it in one place for a quick glance.</div>
<div id="healthtiles" class="tiles"></div></div>
<div class="card" id="ironRulesCard"><h3>Iron Rules / Qualification Tiers</h3>
<div class="note">Iron Rules count is a live count of "## 鐵則 N" headers in
<code>.claude/skills/CORE/iron-rules/SKILL.md</code>. Qualification tiers below are the static 8-tier
vocabulary from <code>dv_harness/qualification.py</code>'s <code>QualificationTier</code> enum, each
tile classed against <code>qualification_tier_reached</code> -- the highest tier actually reached by
any protocol in this run's real <code>protocol_capability_registry.json</code> (tiers at/below that
level render <code>tier-reached</code>, tiers above it render <code>tier-unreached</code>).</div>
<div id="ironrulestiles" class="tiles" style="margin-top:8px"></div>
<div class="note" style="margin-top:8px">Tier ladder (lowest -&gt; highest): <span id="qualtierlegend"></span></div>
</div>
<div class="card" id="dvReviewCard"><h3>DV Review</h3><div id="dvtiles" class="tiles"></div>
<ul id="dvfields" class="note" style="margin:8px 0 0;padding-left:18px"></ul>
<div class="note" style="margin-top:8px">Durably co-sign a pending field (field_path is "&lt;gate_id&gt;/&lt;location&gt;" from the list above, e.g. <code>corner_risk_rank/cases[0].risk_factors</code>) so the NEXT evaluation of this stage accepts it -- matched by EXACT value equality at that location; a value that changes later needs a fresh co-sign. This does not retroactively re-evaluate the CURRENT stage result.</div>
<div class="ctrlrow"><select id="cosignStage"></select>
  <input id="cosignFieldPath" size="26" placeholder="gate_id/location">
  <input id="cosignValue" size="20" placeholder='value as JSON, e.g. "HIGH"'>
  <input id="cosignReviewer" size="10" placeholder="reviewer id">
  <select id="cosignConfidence"><option>HIGH</option><option>MEDIUM</option><option>LOW</option></select>
  <button onclick="doCosign()">Co-sign</button></div>
<div id="cosignResult"></div>
<div class="ctrlrow"><label><input type="checkbox" id="cosignEnforceToggle" onchange="doConfigToggle()"> Enforce DV-review co-sign (policy.require_dv_review_cosign)</label></div>
</div>

<div class="card" id="protocolCard"><h3>Protocols</h3>
<div class="note">Real registered protocols (read from
<code>qualification/protocol_capability_registry.json</code>), each showing TWO independent facts.
First line: <code>capability_status</code> -- what generation code exists, derived in
<code>dv_harness/protocol_capability.py</code> from modules verified to import.
<code>GENERIC_SKELETON_ONLY</code> means only the protocol-agnostic skeleton, nothing
protocol-specific; hover a tile for the module name. Second line:
<code>qualification_status</code> -- how far a generated environment has been PROVEN, on
<code>qualification.py</code>'s 8-tier ladder. Only USB is <code>DUT_PROVEN</code>; no other
protocol has been bound to real RTL. Click a tile to fill the Goal field below with a start-run
goal scoped to that protocol (the exact <code>goal</code> field POST /api/start already reads).</div>
<div id="protocoltiles" class="tiles" style="margin-top:8px"></div>
</div>
<div class="card" id="envModeCard"><h3>Environment Mode Router</h3>
<div class="note">The two canonical modes CLAUDE.md's Environment Generation Mode gate defines
(<code>environment-router/environment_mode_policy.json</code>), with the tile matching
<code>environment_mode_selected</code> highlighted, IF any stage has ever recorded a
<code>dv-harness-evidence:environment_mode_selection</code> block. PROJECT_MODEL now mandates this
block (<code>environment_mode_selection_gate</code>), computed for real per-run from
<code>dv_harness/environment_mode_router.py</code>'s <code>resolve_environment_mode()</code> -- see
<code>_environment_mode_selected()</code> in dashboard.py.</div>
<div id="envmodetiles" class="tiles" style="margin-top:8px"></div>
</div>
<div class="card" id="subsystemRegistryCard"><h3>Subsystem Registry</h3>
<div class="note">Real registered subsystem environments
(<code>soc-composer/subsystem_environment_registry.json</code>), written by engine.py's
<code>_persist_subsystem_registry_entry()</code> on a SIGNOFF PASS carrying
<code>subsystem_environment_registration_gate</code> evidence.</div>
<div style="overflow-x:auto"><table id="subsystemTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:6px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">Name</th><th style="padding:4px">Version/SHA</th><th style="padding:4px">Qualification</th></tr></thead>
<tbody id="subsystemTableBody"></tbody></table></div>
</div>
<div class="card"><h3>Run</h3>
<div class="note" id="runStatusNote"></div>
<div class="ctrlrow">
  <label>Goal <input id="goalInput" size="50" placeholder="e.g. verify the USB device controller"></label>
  <button id="startLoopBtn" onclick="doStart(true)">Start (loop)</button>
  <button id="startSingleBtn" onclick="doStart(false)" class="secondary">Start (single stage)</button>
</div>
<div id="runResult"></div>
</div>

<div class="card"><h3>Control Plane</h3>
<div class="ctrlrow"><button onclick="doControl('PAUSE',{reason:val('pauseReason')})">Pause</button>
  <input id="pauseReason" placeholder="reason"></div>
<div class="ctrlrow"><button onclick="doControl('RESUME',{})">Resume</button></div>
<div class="ctrlrow"><button onclick="doControl('TAKEOVER',{message:val('takeoverMsg')})">Takeover</button>
  <input id="takeoverMsg" size="30" placeholder="message"></div>
<div class="ctrlrow"><button onclick="doControl('RELEASE_TAKEOVER',{})">Release Takeover</button></div>
<div class="ctrlrow"><button onclick="doControl('REDIRECT',{stage:val('redirectStage'),reason:val('redirectReason')})">Redirect</button>
  <select id="redirectStage"></select><input id="redirectReason" size="30" placeholder="reason"></div>
<div class="ctrlrow"><button onclick="doControl('APPROVE',{stage:val('approveStage'),note:val('approveNote'),reviewer_id:val('approveReviewer'),reviewer_confidence:val('approveConfidence')})">Approve</button>
  <select id="approveStage"></select>
  <input id="approveNote" size="24" placeholder="note">
  <input id="approveReviewer" size="12" placeholder="reviewer id">
  <select id="approveConfidence"><option>HIGH</option><option>MEDIUM</option><option>LOW</option></select></div>
<div class="ctrlrow"><button onclick="doControl('CORRECT',{stage:val('correctStage'),note:val('correctNote'),reset_attempts:document.getElementById('correctReset').checked})">Correct</button>
  <select id="correctStage"></select>
  <input id="correctNote" size="30" placeholder="note (required)">
  <label><input type="checkbox" id="correctReset"> reset attempts</label></div>
<div class="ctrlrow"><button onclick="doControl('CONSTRAINT_ADD',{text:val('constraintText')})">Add Constraint</button>
  <input id="constraintText" size="30" placeholder="constraint text"></div>
<div class="ctrlrow"><button onclick="doControl('CONSTRAINT_REMOVE',{constraint_id:val('constraintId')})">Remove Constraint</button>
  <input id="constraintId" size="10" placeholder="constraint id (e.g. CN1)"></div>
<div id="controlResult"></div>
<div class="note" style="margin-top:10px">CLI-only, deliberately-ungated admin operations exist outside this GUI: <code>mark</code>, <code>set-stage</code>, <code>advance</code> bypass every gate on purpose (see cli.py's comment on them) and are intentionally NOT exposed as buttons here -- the CLI has capabilities this GUI does not expose. <code>dv-harness cosign</code>, <code>lsf</code>, <code>audit</code>, and <code>config set/get</code> also exist as CLI subcommands, but each has a GUI equivalent elsewhere on this page (DV Review, LSF, and Audit Trail cards). <b>Also currently CLI-only, not an intentional safety exclusion like the three above -- just not yet given a GUI surface:</b> <code>lsf-submit</code>/<code>lsf-kill</code>/<code>lsf-reconcile</code> (real bsub/bkill/bjobs job control, see the LSF card's own note) and <code>knowledge search</code>/<code>deprecate</code>/<code>confirm</code> (only <code>knowledge status</code>/<code>db-info</code> have a GUI equivalent, see the Shared Knowledge Center card).</div>
</div>

<div class="card"><h3>Audit Trail</h3>
<div class="note">Who changed what, when (GET /api/audit?limit=N, CLI <code>dv-harness audit --limit N</code>): the last N events.jsonl entries plus current control.json corrections/approvals/approval_history/cosigns.</div>
<div class="ctrlrow"><label>Limit <input id="auditLimit" value="50" size="4"></label><button onclick="loadAudit()">Refresh</button></div>
<pre id="auditResult" style="white-space:pre-wrap;font-size:12px;background:#f7f9fc;border:1px solid #e3e9f2;border-radius:6px;padding:8px;margin-top:8px;max-height:320px;overflow:auto"></pre>
</div>

<div class="card" id="guiAuditLogCard"><h3>GUI Action Audit Log</h3>
<div class="note">Structured 7-field record (<b>who</b> / <b>when</b> / <b>before</b> / <b>after</b> /
<b>evidence</b> / <b>approval</b> / <b>result</b>) for every dashboard-issued <code>/api/control</code>
command -- <code>gui_audit_log.py</code>'s own real, evidence-gated records (GET /api/gui-audit-log,
CLI <code>dv-harness gui-audit-log show</code>). Same <code>events.jsonl</code> entries the generic
Audit Trail card above already reads, filtered to this richer per-record shape -- never a second
store. <b>Read-only</b>: this card runs no build, job, or approval.</div>
<div class="ctrlrow"><label>Limit <input id="guiAuditLogLimit" value="50" size="4"></label>
<label>Action <input id="guiAuditLogAction" placeholder="e.g. APPROVE" size="16"></label>
<button onclick="loadGuiAuditLog()">Refresh</button></div>
<div id="guiAuditLogTiles" class="tiles" style="margin-top:8px"></div>
<div style="overflow-x:auto"><table id="guiAuditLogTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:4px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">When</th><th style="padding:4px">Action</th><th style="padding:4px">Who</th>
<th style="padding:4px">Result</th><th style="padding:4px">Approval</th><th style="padding:4px"></th></tr></thead>
<tbody id="guiAuditLogBody"></tbody></table></div>
</div>

<div class="card" id="humanGateCenterCard"><h3>Human Gate Center</h3>
<div class="note">Every consequential dashboard action, centralized: <code>gui_action_safety.py</code>'s
real 11 categories / 21 declared actions (GET /api/human-gate-center), each with its own already-real
<b>scope</b> (the real file/state it mutates), <b>impact</b>, required role, and whether it is
<b>reversible</b> plus its <b>rollback plan kind</b> -- read verbatim off that module's own
declarations, never re-classified here. Below that: real, already-recorded <code>control.json</code>
approval status for the governance stages this project's engine actually consults an approval for
(<code>RESEARCH_CAPABILITY_EVOLUTION</code> / <code>CHANGE_BLAST_RADIUS</code> /
<code>BOUNDED_SELF_HEALING</code>, plus the current stage). <b>Read-only</b>: this card runs no build,
job, or approval itself and duplicates no gate -- approving happens ONLY through the existing
<b>Control Plane</b> card's Approve button above, which calls the same real
<code>ControlPlane.approve()</code> every other approval on this page already goes through; clicking
"Approve this" below only scrolls to and pre-fills that existing form.</div>
<div id="humanGateCenterTiles" class="tiles" style="margin-top:8px"></div>
<div class="ctrlrow" style="margin-top:6px"><button onclick="loadHumanGateCenter()">Refresh</button></div>
<div class="note" style="margin-top:12px"><b>Pending / Recorded Governance Approvals</b></div>
<div style="overflow-x:auto"><table id="humanGateStagesTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:4px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">Stage</th><th style="padding:4px">Status</th><th style="padding:4px">Reviewer</th>
<th style="padding:4px">Confidence</th><th style="padding:4px">Approved At</th><th style="padding:4px">Note</th>
<th style="padding:4px">Prior Approvals</th><th style="padding:4px"></th></tr></thead>
<tbody id="humanGateStagesBody"></tbody></table></div>
<div class="note" style="margin-top:12px"><b>Declared Consequential Actions</b> (11 categories, 21 actions)</div>
<div style="overflow-x:auto"><table id="humanGateDeclarationsTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:4px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">Action</th><th style="padding:4px">Category</th><th style="padding:4px">Required Role</th>
<th style="padding:4px">Impact</th><th style="padding:4px">Reversible</th><th style="padding:4px">Rollback Kind</th>
<th style="padding:4px">Scope</th><th style="padding:4px">Note</th></tr></thead>
<tbody id="humanGateDeclarationsBody"></tbody></table></div>
</div>

<div class="card"><h3>Stage Execution Profile</h3>
<div class="note">Read-only (GET /api/stage-profile, CLI <code>dv-harness stage-profile</code>): per-stage
wall-clock/token/tool-call/retry counts plus aggregate parallelism efficiency, from data this run's engine
already collected -- not a separate measurement.</div>
<div class="ctrlrow"><button onclick="loadStageProfile()">Refresh</button></div>
<pre id="stageProfileResult" style="white-space:pre-wrap;font-size:12px;background:#f7f9fc;border:1px solid #e3e9f2;border-radius:6px;padding:8px;margin-top:8px;max-height:320px;overflow:auto"></pre>
</div>

<div class="card"><h3>Self-Audit</h3>
<div class="note">Read-only: runs the 23 harness self-audit gates (registry/skill/pipeline/protocol-catalog meta-consistency, GET /api/self-audit, CLI <code>dv-harness self-audit</code>) against the harness's OWN current repo state -- not this run's per-DUT stage evidence. A gate with no real harness-state source file reports NO_SOURCE_DATA honestly rather than a fabricated PASS; check "Smoke" to instead prove such a gate's SCRIPT still runs against a constructed representative payload (SCRIPT_SMOKE_PASS/FAIL -- not a verdict on current state).</div>
<div class="ctrlrow"><button onclick="loadSelfAudit()">Run Self-Audit</button>
  <label><input type="checkbox" id="selfAuditSmoke"> Smoke (script health-check for NO_SOURCE_DATA gates)</label></div>
<div id="selfAuditTiles" class="tiles" style="margin-top:8px"></div>
<div style="overflow-x:auto"><table id="selfAuditTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:6px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">Gate</th><th style="padding:4px">Status</th><th style="padding:4px">Mode</th><th style="padding:4px">Detail</th></tr></thead>
<tbody id="selfAuditTableBody"></tbody></table></div>
</div>

<div class="card" id="fsdbReportCard"><h3>FSDB Structured Evidence</h3>
<div class="note">Real signal-level evidence from an FSDB waveform dump via the confirmed-real
<code>fsdbreport f.fsdb -period &lt;T&gt; -level 1 -csv</code> invocation (GET /api/fsdb-report,
dv-workflow/SKILL.md's 2026-08-29 "Confirmed drift" entry) -- a structured evidence TABLE, not a
waveform/timeline viewer (FSDB is a proprietary binary format with no public library, so a real
signal-timeline renderer is out of scope). Column names below come verbatim from whatever real
fsdbreport's -csv output actually declares -- never a hardcoded/guessed schema.</div>
<div class="ctrlrow"><label>Path <input id="fsdbPath" size="34" placeholder="/path/to/dump.fsdb"></label>
  <label>Period <input id="fsdbPeriod" size="10" placeholder="e.g. 100ns"></label>
  <label>Hierarchy <input id="fsdbHier" size="18" placeholder="e.g. top.dut"></label>
  <button onclick="loadFsdbReport()">Run fsdbreport</button></div>
<div class="ctrlrow" style="margin-top:6px"><label>Filter by signal name
  <input id="fsdbSignalFilter" size="24" oninput="renderFsdbReportTable()" placeholder="substring filter"></label></div>
<div id="fsdbReportResult" class="note" style="margin-top:6px"></div>
<div style="overflow-x:auto"><table id="fsdbReportTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:6px">
<thead id="fsdbReportTableHead"><tr style="text-align:left;border-bottom:1px solid #d9e1ec"></tr></thead>
<tbody id="fsdbReportTableBody"></tbody></table></div>
</div>

<div class="card" id="loopCenterCard"><h3>Loop Engineering Center</h3>
<div class="note">Section 107's <code>Loop | State | Iteration | Verified Gain | Budget | Plateau |
Oscillation | Next Action</code> table, folded out of the REAL section-108 loop telemetry events
<code>engine.DVHarness.loop()</code> writes to <code>.dv-harness/events.jsonl</code> -- the same
append-only audit trail the Audit card on this page reads, not a second log
(GET /api/loops). One row per loop SESSION, newest first.
<br><b>Nothing on this card is derived here.</b> The State is
<code>loop_contract.derive_loop_state()</code>'s, the Plateau/Oscillation verdict is
<code>loop_convergence.classify_loop_convergence()</code>'s over the project's own evidence
database, the Budget is <code>policy.max_stage_retries</code> plus
<code>loop_budget</code>'s unified ledger, the Verified Gain counts stages whose gates really
accepted their evidence, and the Next Action comes from the real
<code>inference.next_best_action()</code>. Each number reached this page as the payload of an
event the mechanism that owns it emitted.
<br><b>Two different progress metrics, never conflated.</b>
<code>gate_verified_stages</code> is per-iteration (this engine's only per-iteration verified
signal); <code>coverage_percent</code> is the cross-run series plateau is measured on, classified
once per retry exhaustion. Every event carries which one produced it.
<br>Read-only: this card starts, stops and approves nothing -- the run controls are at the top of
the page and every human gate stays exactly where it was. A project whose loops have never emitted
an event shows an honest empty state naming the file it read and the command that would populate
it, never a fabricated row.</div>
<div class="ctrlrow" style="margin-top:6px"><button onclick="loadLoopCenter()">Refresh</button>
  <span class="note" id="loopCenterScan"></span></div>
<div class="note" id="loopCenterNote" style="margin-top:6px"></div>
<div style="overflow-x:auto"><table id="loopCenterTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:6px">
<thead id="loopCenterTableHead"><tr style="text-align:left;border-bottom:1px solid #d9e1ec"></tr></thead>
<tbody id="loopCenterTableBody"></tbody></table></div>
<pre id="loopCenterDetail" style="display:none;white-space:pre-wrap;font-size:12px;background:#f7f9fc;border:1px solid #e3e9f2;border-radius:6px;padding:8px;margin-top:8px;max-height:420px;overflow:auto"></pre>
</div>

<div class="card" id="agentActivityCard"><h3>Agent Activity</h3>
<div class="note">GUI-06's Agent/Current State/Current Action/Owned Task/Last Update columns, read
directly off the real <code>AgentTaskStore</code> delegation ledger (GET /api/agent-activity, reading
<code>.dv-harness/agents/tasks.json</code>/<code>ownership.json</code>): one row per real task
<code>engine.DVHarness.run_stage()</code> delegated through <code>MultiAgentOrchestrator.delegate()</code>
before every LLM call, with real <code>start_task()</code>/<code>complete_task()</code> timing. Current
Action is the resolved skill ROUTE (e.g. <code>implementation-route</code>), not the stage id -- this
store never records which graph stage a task belongs to, so it cannot be joined to a stage. Owned
Task lists the real blackboard-topic/resource claims <code>ownership.json</code> attributes to that
exact <code>task_id</code> (a fan-out branch's claim on a shared write topic, never a name guess).
Evidence/Confidence/Blocking Reason/Next-Best-Action for the CURRENT stage are already real and shown
elsewhere on this page (Why (current stage), Findings, Hypothesis &amp; Review) rather than duplicated
here under an unproven per-task correlation -- see this card's own note in dashboard.py for why no
such join is attempted. No task delegated yet shows an honest empty state below, never a fabricated
agent row.</div>
<div id="agentActivityTiles" class="tiles" style="margin-top:8px"></div>
<div style="overflow-x:auto"><table id="agentActivityTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:6px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">Task</th><th style="padding:4px">Agent</th><th style="padding:4px">Current Action (route)</th>
<th style="padding:4px">Skills</th><th style="padding:4px">Parallel Group</th><th style="padding:4px">Owned Task (claims)</th>
<th style="padding:4px">Current State</th><th style="padding:4px">Last Update</th></tr></thead>
<tbody id="agentActivityTableBody"></tbody></table></div>
</div>

<div class="card" id="resourceOrchestratorCard"><h3>Resource Orchestrator (VI-5 Cross-Job Grant Ranking)</h3>
<div class="note">Real <code>resource_orchestrator.orchestrate()</code> output (GET /api/resource-orchestrator,
reading <code>.dv-harness/resource_orchestrator/plan_inputs.json</code>): a real, ranked
GRANTED/QUEUED/DEFERRED arbitration plan over N declared cross-job/cross-project contenders and
ONE measured license/queue capacity -- never a second, dashboard-local arbitration engine. A GRANT
authorizes nothing (see this module's own disclosure below): every existing preflight/approval gate
still stands in front of any real work. With no <code>requests</code> declared, contenders are built
from the real cross-project registry (<code>contenders_from_registry()</code>); an empty registry
with nothing declared shows an honest empty state, never a fabricated plan.
<b>Read-only</b>: this card runs no build, submission, or approval of its own.</div>
<div id="resourceOrchestratorTiles" class="tiles" style="margin-top:8px"></div>
<div style="overflow-x:auto"><table id="resourceOrchestratorTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:6px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">Rank</th><th style="padding:4px">Project / Stage</th><th style="padding:4px">Decision</th>
<th style="padding:4px">Priority</th><th style="padding:4px">Held Slots</th><th style="padding:4px">Reason</th></tr></thead>
<tbody id="resourceOrchestratorBody"></tbody></table></div>
<div class="note" id="resourceOrchestratorSkippedNote" style="margin-top:8px"></div>
<div class="note" id="resourceOrchestratorDisclosureNote" style="margin-top:4px"></div>
</div>

<div class="card" id="memoryCenterCard"><h3>Memory + Obsidian Knowledge Center</h3>
<div class="note">Real record counts for all five Memory Hierarchy tiers
(<code>memory.MEMORY_LEVELS</code>: Working / Job / Project / Engineering / Organizational) plus a
real browse/search over the DV-Knowledge Vault notes <code>memory_vault.py</code> mirrors those
records into (GET /api/memory). Per-tier counts are
<code>MemoryStore.index_integrity()</code>'s own <code>per_level</code> figures -- the same read-only
report <code>dv-harness memory doctor</code>'s <code>memory_store_index</code> check reads, so
<b>record files</b> (what is really on disk) and <b>index rows</b> (what
<code>MemoryRetriever.search()</code> can actually find) stay two separate numbers: a tier where they
disagree has records that exist but are invisible to search. Vault notes are read through the real
<code>memory_vault.get_active_provider()</code> and its own <code>search()</code>/<code>read()</code>
-- no markdown or YAML frontmatter is parsed in dashboard.py.
<br><b>Organizational is deliberately not a local file store.</b>
<code>memory_router.route_and_store()</code> sends ORGANIZATIONAL_MEMORY straight to the shared,
cross-user Knowledge Center instead of <code>.dv-harness/memory/organizational/</code>, so that
tile shows the shared store's real configured/not-configured state rather than a local count of 0
that would read as "no organizational knowledge exists". That shared store's own connectivity is
the separate <b>Shared Knowledge Center</b> card below; this card is about what THIS project's
memory tiers hold.
<br>Read-only: authoring a record or a note stays CLI-only
(<code>dv-harness memory add</code>) and the engine's own promotion write-through -- what enters a
durable knowledge tier is gated on real verification evidence, never on a browser form. No memory
store and no vault yet shows an honest empty state naming both paths looked at, never a fabricated
count.</div>
<div id="memoryTiles" class="tiles" style="margin-top:8px"></div>
<div class="note" id="memoryIntegrityNote" style="margin-top:8px"></div>
<div class="ctrlrow" style="margin-top:6px"><label>Search vault notes
  <input id="memoryNoteQuery" size="26" placeholder="keyword / free text"></label>
  <label>Tier <select id="memoryLevelFilter"><option value="">(any tier)</option></select></label>
  <button onclick="loadMemoryCenter()">Search</button></div>
<div style="overflow-x:auto"><table id="memoryNotesTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:6px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">Note</th><th style="padding:4px">Failure / root cause</th><th style="padding:4px">Tier</th>
<th style="padding:4px">Protocol</th><th style="padding:4px">Status</th>
<th style="padding:4px">Confidence</th><th style="padding:4px">Updated</th>
<th style="padding:4px">Path</th></tr></thead>
<tbody id="memoryNotesTableBody"></tbody></table></div>
<pre id="memoryNoteDetail" style="display:none;white-space:pre-wrap;font-size:12px;background:#f7f9fc;border:1px solid #e3e9f2;border-radius:6px;padding:8px;margin-top:8px;max-height:360px;overflow:auto"></pre>
</div>

<div class="card"><h3>Shared Knowledge Center</h3>
<div class="note">Read-only status (GET /api/knowledge/status). Choosing/typing the shared
Linux-server path is CLI-only by design: <code>dv-harness knowledge setup</code> always
interactively ASKS for the path (CLAUDE.md's SSH/Remote Transport Connection Intake rule) --
this GUI panel never sets or guesses it, only reports what is already configured.</div>
<div class="ctrlrow"><button onclick="loadKnowledgeStatus()">Refresh</button>
  <button onclick="loadDbInfo()">DB Info (who added/updated/deleted, when)</button></div>
<pre id="knowledgeStatusResult" style="white-space:pre-wrap;font-size:12px;background:#f7f9fc;border:1px solid #e3e9f2;border-radius:6px;padding:8px;margin-top:8px;max-height:220px;overflow:auto"></pre>
<div style="overflow-x:auto"><table id="dbInfoTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:6px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">When</th><th style="padding:4px">Action</th><th style="padding:4px">Record</th>
<th style="padding:4px">Category/Protocol</th><th style="padding:4px">User</th><th style="padding:4px">Summary</th></tr></thead>
<tbody id="dbInfoTableBody"></tbody></table></div>
</div>

<div class="card"><h3>User Info</h3>
<div class="note">Who has used THIS deployment (this project root), and when -- inferred login/logout
sessions from CLI_ACCESS/GUI_ACCESS events (a gap &gt; 30 min starts a new session; neither the CLI
nor a stateless HTTP GUI has a real logout signal, so "logout" here means "last seen before going
quiet", not a guaranteed exact instant).</div>
<div class="ctrlrow"><button onclick="loadUserInfo()">Refresh</button></div>
<div style="overflow-x:auto"><table id="userInfoTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:6px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">User</th><th style="padding:4px">Sessions</th><th style="padding:4px">First seen</th>
<th style="padding:4px">Last seen (login/logout)</th></tr></thead>
<tbody id="userInfoTableBody"></tbody></table></div>
</div>

<div class="card"><h3>Session Save / Restore</h3>
<div class="note">Snapshots the current run-state layer (state/control/blackboard/plans/react/agents/
telemetry/config) under <code>.dv-harness/sessions/&lt;name&gt;/</code> -- never the Memory Hierarchy or
Corner-Case Library (durable knowledge, not session state). Restore auto-backs-up whatever it
overwrites first, so it is never one-way.</div>
<div class="ctrlrow"><input id="sessionSaveName" placeholder="name (optional, e.g. checkpoint1)" size="20">
  <input id="sessionSaveNote" placeholder="note (optional)" size="24">
  <button onclick="saveSession()">Save Session</button></div>
<div id="sessionSaveResult" style="font-size:12px;margin-top:4px"></div>
<div class="ctrlrow" style="margin-top:8px"><button onclick="loadSessions()">Refresh list</button></div>
<div style="overflow-x:auto"><table id="sessionTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:6px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">Name</th><th style="padding:4px">Saved</th><th style="padding:4px">Stage</th>
<th style="padding:4px">Note</th><th style="padding:4px">By</th><th style="padding:4px"></th></tr></thead>
<tbody id="sessionTableBody"></tbody></table></div>
</div>

<div class="card" id="signoffExportCard"><h3>Signoff Export</h3>
<div class="note">One-click bundle of real signoff artifacts (blackboard state, vPlan, a freshly-generated
self-audit result, stage-execution telemetry, pattern registry, generated UVM testbench source,
regression/test-suite manifest) into a single directory -- mirrors
<code>signoff_export.collect_signoff_bundle()</code> directly (same-process, no subprocess). Each candidate
artifact is copied only if it actually exists on disk; <code>manifest.json</code> in the output directory
records present/absent honestly, never a fabricated placeholder. Leave out_dir blank for a default under
<code>.dv-harness/signoff-export/&lt;timestamp&gt;/</code>.</div>
<div class="ctrlrow"><input id="signoffExportOutDir" placeholder="out_dir (optional, absolute path)" size="40">
  <button onclick="doSignoffExport()">Export Signoff Bundle</button></div>
<div id="signoffExportResult" style="font-size:12px;margin-top:4px"></div>
</div>

<div class="card" id="waiverCard"><h3>Waiver Authoring</h3>
<div class="note">Human-authored waivers, persisted to <code>.dv-harness/waivers/waivers.json</code>
(POST /api/waiver, <code>waiver_store.append_waiver()</code>). Since 2026-09-06 this store is the
SOURCE OF TRUTH the three waiver gate scripts read from: whenever this file exists,
<code>waiver_scope_consistency_gate</code>, <code>waiver_revision_freshness_gate</code> and
<code>waiver_revalidation_gate</code> judge THESE records rather than the agent's own fenced
<code>dv-harness-evidence:&lt;gate_id&gt;</code> block, and a waiver_id the agent cites that is not
recorded here FAILs <code>WAIVER_NOT_IN_STORE</code>. A recorded waiver is therefore re-evaluated on
every run -- when it expires or its revalidation trigger fires, the requirement it was waiving is
re-flagged whether or not anyone mentions it (spec section 237).
<b>Fill in Waiver ID and the section 237 fields below</b> to record a real waiver: a submission
carrying only Gate/Item/Evidence is still accepted (the original 4-field shape) but cannot be shown
to still be valid, so the gates report it <code>WAIVER_STATUS_UNKNOWN</code>. Status
(VALID / REVALIDATION_REQUIRED / EXPIRED / REVOKED / UNKNOWN) is always DERIVED from the record's own
content -- it is never stored, and a submission that tries to store one is rejected with a 400.
Inspect what is recorded with <code>python -m dv_harness.waiver_store status</code>.</div>
<div class="ctrlrow">
  <label>Gate <select id="waiverGateId">
    <option value="waiver_scope_consistency_gate">waiver_scope_consistency_gate</option>
    <option value="waiver_revision_freshness_gate">waiver_revision_freshness_gate</option>
    <option value="waiver_revalidation_gate">waiver_revalidation_gate</option>
    <option value="coverage_hole_regeneration_gate">coverage_hole_regeneration_gate</option>
    <option value="coverage_hole_to_test_generation_gate">coverage_hole_to_test_generation_gate</option>
    <option value="sequence_coverage_closure_gate">sequence_coverage_closure_gate</option>
  </select></label>
  <label>Item ID <input id="waiverItemId" size="24" placeholder="e.g. cov-hole-42"></label>
</div>
<div class="ctrlrow"><label style="align-items:flex-start">Evidence
  <textarea id="waiverEvidence" rows="3" cols="60" placeholder="why this item is genuinely waived (reviewer, spec section, rationale)"></textarea></label></div>
<div class="ctrlrow">
  <label>Waiver ID <input id="waiverId" size="18" placeholder="e.g. W-USB-001"></label>
  <label>Approver <input id="waiverApprover" size="16" placeholder="who approved it"></label>
  <label>Risk <select id="waiverRisk">
    <option value="LOW">LOW</option><option value="MEDIUM">MEDIUM</option><option value="HIGH">HIGH</option>
  </select></label>
  <label>Expires at <input id="waiverExpiresAt" size="26" placeholder="2026-12-31T00:00:00+00:00"></label>
</div>
<div class="ctrlrow">
  <label>Reason <input id="waiverReason" size="40" placeholder="why the DUT cannot satisfy this requirement"></label>
  <label>Requirement IDs <input id="waiverRequirementIds" size="24" placeholder="REQ-1,REQ-2"></label>
  <label>Subsystem <input id="waiverSubsystem" size="14"></label>
</div>
<div class="ctrlrow">
  <label>Spec revision <input id="waiverSpecRevision" size="12"></label>
  <label>RTL hash <input id="waiverRtlHash" size="14"></label>
  <label>Revision <input id="waiverRevision" size="10"></label>
  <label>Approval ID <input id="waiverApprovalId" size="12"></label>
</div>
<div class="ctrlrow">
  <label>Design evidence hash <input id="waiverDesignEvidenceHash" size="22"></label>
  <label>Scope hash <input id="waiverScopeHash" size="22"></label>
</div>
<div class="ctrlrow"><label><input type="checkbox" id="waiverApproved" checked> Approved</label>
  <button onclick="doWaiverSubmit()">Submit Waiver</button></div>
<div id="waiverResult" style="font-size:12px;margin-top:4px"></div>
</div>

<div class="card" id="changeImpactCard"><h3>Change Impact View</h3>
<div class="note">Real <code>change_impact.py</code> CHANGE -&gt; DESIGN -&gt; REQUIREMENT/VPLAN/PATTERN/
COVERAGE impact for the project's current diff (GET /api/change-impact, reading
<code>.dv-harness/regression/computed_selection.json</code> verbatim off
<code>read_computed_selection()</code> -- never a dashboard-local re-classification of risk or
confidence). Populated by REGRESSION_SELECT's real <code>compute_and_write()</code> call.
<b>Read-only</b>: no <code>git diff</code> is run here.</div>
<div id="changeImpactTiles" class="tiles" style="margin-top:8px"></div>
<div class="ctrlrow" style="margin-top:6px"><button onclick="loadChangeImpact()">Refresh</button></div>
<div style="overflow-x:auto"><table id="changeImpactTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:6px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">Changed File</th><th style="padding:4px">Impacted Area</th><th style="padding:4px">Risk</th>
<th style="padding:4px">Confidence</th><th style="padding:4px">REQ_ID</th><th style="padding:4px">PATTERN_ID</th></tr></thead>
<tbody id="changeImpactTableBody"></tbody></table></div>
<div class="note" id="changeImpactNote" style="margin-top:8px"></div>
</div>

<div class="card" id="regressionTierCard"><h3>Minimum Safe Regression View</h3>
<div class="note">Real <code>regression_tiers.py</code> tiered-cadence policy (SMOKE/NIGHTLY/WEEKLY:
selection classes, time budget, UVM_FATAL burst threshold), plus, when a tier is currently
declared active, the real MINIMUM-SAFE test set that tier resolves via <code>tests_for_tier()</code>
(GET /api/regression-tier). <b>Read-only</b>: no regression is submitted here.</div>
<div id="regressionTierTiles" class="tiles" style="margin-top:8px"></div>
<div class="ctrlrow" style="margin-top:6px"><button onclick="loadRegressionTier()">Refresh</button></div>
<div style="overflow-x:auto"><table id="regressionTierPolicyTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:6px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">Tier</th><th style="padding:4px">Cadence</th><th style="padding:4px">Budget (min)</th>
<th style="padding:4px">UVM_FATAL Threshold</th><th style="padding:4px">Classes</th></tr></thead>
<tbody id="regressionTierPolicyBody"></tbody></table></div>
<div class="note" style="margin-top:8px" id="regressionTierMinSafeNote"></div>
<div style="overflow-x:auto"><table id="regressionTierMinSafeTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:4px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">#</th><th style="padding:4px">Pattern</th></tr></thead>
<tbody id="regressionTierMinSafeBody"></tbody></table></div>
</div>

<div class="card" id="notificationCenterCard"><h3>Notification Center</h3>
<div class="note">Real escalation configuration (<code>escalation_notify.py</code> -- never a live
network probe: no transport is constructed here) plus the project's own persisted
change-only notification history (<code>harness_status.py</code>'s HARNESS_STATUS_SNAPSHOT records,
filtered to entries whose real <code>transitioned</code> field is True -- an unchanged state is
never re-shown here, the same discipline <code>escalation_notify.py</code>'s own <code>_fire()</code>
already enforces). GET /api/notifications. <b>Read-only</b>.</div>
<div id="notificationCenterTiles" class="tiles" style="margin-top:8px"></div>
<div class="ctrlrow" style="margin-top:6px"><button onclick="loadNotificationCenter()">Refresh</button></div>
<div style="overflow-x:auto"><table id="notificationCenterTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:6px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">When</th><th style="padding:4px">Previous State</th><th style="padding:4px">New State</th>
<th style="padding:4px">Signoff State</th><th style="padding:4px">Trigger</th></tr></thead>
<tbody id="notificationCenterTableBody"></tbody></table></div>
<div class="note" id="notificationCenterNote" style="margin-top:8px"></div>
</div>

<div class="card" id="observabilityCard"><h3>GUI Observability</h3>
<div class="note">This dashboard PROCESS's own self-measured API route latency (recorded once per
response by this same process; empty for a route never yet served) and the real
<code>.dv-harness/events.jsonl</code> backlog/staleness (reused from
<code>loop_telemetry.read_events()</code>, never a second parser). GET /api/observability.
<b>Read-only</b>.</div>
<div id="observabilityTiles" class="tiles" style="margin-top:8px"></div>
<div class="ctrlrow" style="margin-top:6px"><button onclick="loadObservability()">Refresh</button></div>
<div style="overflow-x:auto"><table id="observabilityRouteTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:6px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">Route</th><th style="padding:4px">Samples</th><th style="padding:4px">Last (ms)</th>
<th style="padding:4px">Avg (ms)</th><th style="padding:4px">p50 (ms)</th><th style="padding:4px">Max (ms)</th></tr></thead>
<tbody id="observabilityRouteBody"></tbody></table></div>
<div class="note" id="observabilityNote" style="margin-top:8px"></div>
</div>

<div class="card" id="dependencySupplyChainCard"><h3>Dependency / Supply-Chain Governance</h3>
<div class="note">Real <code>dependency_supply_chain.analyze_supply_chain()</code> output (GET
/api/dependency-supply-chain): this project's own declared Python dependencies (pyproject.toml /
requirements*.txt) plus, when <code>$DESIGNWARE_HOME</code> is set, its real installed DesignWare
VIP packages -- checked for pin status, declared-vs-REALLY-INSTALLED resolution against this
interpreter, and (only with a real offline advisory database configured) a vulnerability-advisory
lookup. An advisory check with no offline database reports <b>NOT_AVAILABLE</b>, never a fabricated
clean result -- no network advisory API is ever contacted. <b>Read-only</b>: this card runs no build,
simulation, or gate.</div>
<div id="dependencySupplyChainTiles" class="tiles" style="margin-top:8px"></div>
<div class="ctrlrow" style="margin-top:6px"><button onclick="loadDependencySupplyChain()">Refresh</button></div>
<div style="overflow-x:auto"><table id="dependencySupplyChainTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:6px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">Component</th><th style="padding:4px">Ecosystem</th><th style="padding:4px">Pin Status</th>
<th style="padding:4px">Declared</th><th style="padding:4px">Installed</th><th style="padding:4px">Resolution</th></tr></thead>
<tbody id="dependencySupplyChainBody"></tbody></table></div>
<div class="note" id="dependencySupplyChainFindingsNote" style="margin-top:8px"></div>
</div>

<div class="card" id="scenarioPatternCorrespondenceCard"><h3>VIP Scenario Pattern &lt;-&gt; command.txt Correspondence</h3>
<div class="note">Real <code>scenario_pattern_command_txt_correspondence.analyze_scenario_pattern_command_txt_correspondence()</code>
output (GET /api/scenario-pattern-command-txt-correspondence): cross-references a real
<code>vip_capability_extraction.json</code> document's declared <code>VIPScenarioPatternIR</code> classes
against a project's real command.txt/pattern <code>branch_b*</code> (VIP-owned) sequence usages. Both
inputs are caller-supplied paths below -- neither has a fixed on-disk convention, so nothing is guessed.
<b>Read-only</b>: runs, builds, submits and approves nothing.</div>
<div class="ctrlrow" style="margin-top:6px">
<input id="scenarioPatternCapabilityReportInput" type="text" placeholder="vip_capability_extraction.json path" style="width:280px">
<input id="scenarioPatternCommandFilesInput" type="text" placeholder="command.txt path(s), comma-separated" style="width:280px">
<button onclick="loadScenarioPatternCorrespondence()">Refresh</button>
</div>
<div id="scenarioPatternCorrespondenceTiles" class="tiles" style="margin-top:8px"></div>
<div style="overflow-x:auto"><table id="scenarioPatternCorrespondenceTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:6px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">branch_b* command</th><th style="padding:4px">Status</th><th style="padding:4px">Matched class</th>
<th style="padding:4px">Match kind</th><th style="padding:4px">Evidence</th></tr></thead>
<tbody id="scenarioPatternCorrespondenceBody"></tbody></table></div>
<div class="note" id="scenarioPatternCorrespondenceNote" style="margin-top:8px"></div>
</div>

<div class="card" id="intakeEventsCard"><h3>Intake Events</h3>
<div class="note">Real <code>intake_events.read_intake_events()</code> output (GET
/api/intake-events): the fixed 18-event <code>INTAKE_*</code> taxonomy over
<code>.dv-harness/events.jsonl</code> -- 13 events mirroring
<code>verification_intake_contract.py</code>'s own 13-state
<code>IntakeContractState</code> lifecycle, plus 5 events over
<code>intake_state.py</code>'s own real per-run findings (a state-built summary,
a per-field BLOCKED/CONTRADICTED event, and the two mutually-exclusive
generation-readiness outcomes). Emission is <b>opt-in</b> on both modules' own
writers (a caller must pass a real <code>store=</code>) -- a project on which
nobody has done so honestly shows zero events here, never a fabricated feed.
<b>Read-only</b>: this card runs no build, simulation, or gate.</div>
<div id="intakeEventsTiles" class="tiles" style="margin-top:8px"></div>
<div class="ctrlrow" style="margin-top:6px"><button onclick="loadIntakeEvents()">Refresh</button></div>
<div style="overflow-x:auto"><table id="intakeEventsTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:6px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">Time</th><th style="padding:4px">Event</th><th style="padding:4px">Payload</th></tr></thead>
<tbody id="intakeEventsBody"></tbody></table></div>
<div class="note" id="intakeEventsNote" style="margin-top:8px"></div>
</div>

<div class="card" id="patternRuntimeStateCard"><h3>Pattern Runtime State Machine</h3>
<div class="note">Real <code>pattern_runtime_state_machine.execute_verb()</code> output (GET
/api/pattern-runtime-state): per-pattern
CREATED&rarr;PARSED&rarr;VALIDATED&rarr;READY&rarr;RUNNING&rarr;WAITING&rarr;CHECKING&rarr;
PASS/FAIL/TIMEOUT/BLOCKED/CANCELLED execution records persisted under
<code>.dv-harness/pattern_runtime/records.json</code>, with the module's own real legal-transition
table shown for reference. Persistence is <b>opt-in</b> on that module's own writers (a caller must
call <code>advance_pattern_state()</code>/<code>save_records()</code> itself) -- a project on which
nobody has done so honestly shows zero records here, never a fabricated feed. <b>Read-only</b>: this
card runs no build, simulation, or gate.</div>
<div id="patternRuntimeStateTiles" class="tiles" style="margin-top:8px"></div>
<div class="ctrlrow" style="margin-top:6px"><button onclick="loadPatternRuntimeState()">Refresh</button></div>
<div style="overflow-x:auto"><table id="patternRuntimeStateTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:6px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">Pattern</th><th style="padding:4px">Protocol</th><th style="padding:4px">State</th>
<th style="padding:4px">Terminal?</th><th style="padding:4px">Transitions</th><th style="padding:4px">Created</th></tr></thead>
<tbody id="patternRuntimeStateBody"></tbody></table></div>
<div class="note" id="patternRuntimeStateNote" style="margin-top:8px"></div>
</div>

<div class="card" id="protocolSelectorCard"><h3>Protocol Selector</h3>
<div class="note">Real <code>protocol_router.resolve_protocol()</code> output (GUI-02, GET
/api/protocol-selector): distinguishes user-declared protocol from what the evidence alone
auto-detects. Reads a caller-declared evidence document at
<code>.dv-harness/protocol_selector/inputs.json</code> (<code>protocol_hint</code>/
<code>failing_test_name</code>/<code>active_config</code>/<code>modified_files</code>/
<code>subsystem_boundary</code>) -- a project with no such file honestly shows nothing here,
never a fabricated protocol. <b>Backend protocol-router remains authoritative</b>: this card
never arbitrates a real user-vs-evidence disagreement, it only surfaces it. <b>Read-only</b>:
this card runs no build, simulation, or gate.</div>
<div id="protocolSelectorTiles" class="tiles" style="margin-top:8px"></div>
<div class="ctrlrow" style="margin-top:6px"><button onclick="loadProtocolSelector()">Refresh</button></div>
<div style="overflow-x:auto"><table id="protocolSelectorTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:6px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">Source</th><th style="padding:4px">Protocol</th><th style="padding:4px">Matched Field</th>
<th style="padding:4px">Evidence</th></tr></thead>
<tbody id="protocolSelectorBody"></tbody></table></div>
<div class="note" id="protocolSelectorNote" style="margin-top:8px"></div>
</div>

<div class="card" id="intakeBaselineCard"><h3>Intake Baseline</h3>
<div class="note">Real <code>intake_baseline.py</code> freeze/list/status card (GET
/api/intake-baseline): every recorded intake-freeze record under
<code>.dv-harness/intake/baselines/*.json</code> (the twelve pre-generation intake
facts -- DUT top/boundary, DUT/TB SHA, source file hashes, VIP declaration, bind
topology hash, reference-UVM hash, DE command.txt hash, known-test list, and the
three unresolved-unknowns/conflicts/decisions counters), plus a real
VALID/INVALIDATED/UNKNOWN re-evaluation against CURRENT facts. That evaluation only
ever runs against a real, on-disk current-facts document (this project's own
<code>.dv-harness/intake/current_facts.json</code>) -- with none present, freezes are
still listed but no evaluation is fabricated. <b>Read-only</b>: this card never
freezes, writes, or gates anything itself.</div>
<div id="intakeBaselineTiles" class="tiles" style="margin-top:8px"></div>
<div class="ctrlrow" style="margin-top:6px"><button onclick="loadIntakeBaseline()">Refresh</button></div>
<div style="overflow-x:auto"><table id="intakeBaselineTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:6px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">Freeze ID</th><th style="padding:4px">Frozen By</th><th style="padding:4px">Frozen At</th>
<th style="padding:4px">Status</th><th style="padding:4px">Invalidating</th><th style="padding:4px">Indeterminate</th></tr></thead>
<tbody id="intakeBaselineBody"></tbody></table></div>
<div class="note" id="intakeBaselineNote" style="margin-top:8px"></div>
</div>

<div class="card" id="patternCoverageContributionCard"><h3>Pattern Coverage Contribution</h3>
<div class="note">Real <code>pattern_coverage_contribution.compute_pattern_coverage_contribution()</code>
output (GET /api/pattern-coverage-contribution): a real, attributed per-pattern marginal coverage
contribution (new bins hit, new <em>meaningful</em> cross bins hit, a bins-weighted
coverage_delta_percent) plus real runtime/failure evidence from <code>evidence_db.py</code>'s
<code>jobs</code> table -- read straight off <code>.dv-harness/evidence/evidence.duckdb</code>, never
re-derived here. <code>sample_attribution</code> is a required, explicit, caller-declared fact this
codebase has NO producer for -- a JSON file of <code>[{"source":..., "pattern":...}, ...]</code>
mapping each real coverage checkpoint's own <code>source</code> value to the pattern that produced it.
With no attribution file supplied, this card honestly reports "attribution required" rather than
inventing one. <b>Read-only</b>: this card runs no build, simulation, or gate.</div>
<div class="ctrlrow"><label>Pattern <input id="pccPattern" size="20" placeholder="e.g. usb3_link_up"></label>
  <label>Attribution JSON <input id="pccAttribution" size="34" placeholder="/path/to/attribution.json"></label>
  <label>Cross Definitions JSON <input id="pccCrossDefs" size="26" placeholder="(optional)"></label>
  <button onclick="loadPatternCoverageContribution()">Compute</button></div>
<div id="patternCoverageContributionTiles" class="tiles" style="margin-top:8px"></div>
<div style="overflow-x:auto"><table id="patternCoverageContributionTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:6px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">Category</th><th style="padding:4px">Before</th><th style="padding:4px">After</th>
<th style="padding:4px">Bins Total</th><th style="padding:4px">New Bins Hit</th></tr></thead>
<tbody id="patternCoverageContributionBody"></tbody></table></div>
<div class="note" id="patternCoverageContributionNote" style="margin-top:8px"></div>
</div>

<div class="card" id="buildRemoteLsfIntakeCard"><h3>Build/Remote/LSF Intake</h3>
<div class="note">Real <code>build_remote_lsf_intake.py</code> readiness card (GET
/api/build-remote-lsf-intake): eda_license_available/lsf_configured/
build_environment_reachable/disk_space_sufficient/workdir_ready/
eda_env_vars_configured/remote_transport_available, each mapped from a real
<code>preflight.py</code> CheckOutcome/TransportDecision. <b>This card NEVER runs a live
probe</b> -- it only reads an already-declared PreflightResult/TransportDecision JSON
document a real <code>preflight.run_preflight()</code> run already wrote elsewhere, at
<code>.dv-harness/build_remote_lsf_intake/preflight_result.json</code>. Absent that
file, this card honestly reports nothing rather than invoking a real network/host/
license/LSF-queue probe on every page load.</div>
<div id="buildRemoteLsfIntakeTiles" class="tiles" style="margin-top:8px"></div>
<div class="ctrlrow" style="margin-top:6px"><button onclick="loadBuildRemoteLsfIntake()">Refresh</button></div>
<div style="overflow-x:auto"><table id="buildRemoteLsfIntakeTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:6px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">Field</th><th style="padding:4px">Status</th><th style="padding:4px">Confidence</th>
<th style="padding:4px">Value</th><th style="padding:4px">Reason</th></tr></thead>
<tbody id="buildRemoteLsfIntakeBody"></tbody></table></div>
<div class="note" id="buildRemoteLsfIntakeNote" style="margin-top:8px"></div>
</div>

<div class="card" id="memoryQualityPolicyCard"><h3>Memory Quality Policy</h3>
<div class="note">Real <code>memory_quality_policy.evaluate_memory_quality()</code> output (GET
/api/memory-quality-policy): which records in this project's own local Memory store the real
age/never-confirmed/duplicate retirement policy would flag <b>FLAG_STALE</b> (aged past the
declared window with no recent confirm/reuse/create), <b>DEPRECATE</b> (never confirmed AND
never reused, well past that same window), or <b>SUPERSEDE</b> (two or more ACTIVE
engineering-tier records found to be the same finding). This is a report only -- it never calls
the `apply` half, so nothing here retires a record; a human runs
<code>dv-harness memory-quality-policy apply</code> themselves after reviewing this list.
A project with no memory store yet honestly reports <b>NOT_AVAILABLE</b>, never a store minted
merely by loading this page.</div>
<div id="memoryQualityPolicyTiles" class="tiles" style="margin-top:8px"></div>
<div class="ctrlrow" style="margin-top:6px"><button onclick="loadMemoryQualityPolicy()">Refresh</button></div>
<div style="overflow-x:auto"><table id="memoryQualityPolicyTable" style="width:100%;border-collapse:collapse;font-size:12px;margin-top:6px">
<thead><tr style="text-align:left;border-bottom:1px solid #d9e1ec">
<th style="padding:4px">Action</th><th style="padding:4px">Memory ID</th><th style="padding:4px">Level</th>
<th style="padding:4px">Status</th><th style="padding:4px">Reason</th></tr></thead>
<tbody id="memoryQualityPolicyBody"></tbody></table></div>
<div class="note" id="memoryQualityPolicyNote" style="margin-top:8px"></div>
</div>

<div class="card"><h3>Graph</h3><div id="graph"></div>
<div class="note">Confidence is not shown here: no single-value "current confidence" field is tracked in HarnessState today (see engineering findings in root_cause/mechanism evidence blocks instead).</div>
</div>
<div class="card"><h3>DE 白話說明</h3>
<div class="note">給沒有 UVM/DV 背景的人看的說明；點下方任一 stage 節點可切換。不影響實際 gate 判定。</div>
<div id="deexplain" style="white-space:pre-wrap;font-size:13px;margin-top:8px"></div>
</div>
</main>
<script>
function tile(n,l){return `<div class="tile"><div class="n">${n}</div><div class="l">${l}</div></div>`}
function icon(status){
  if(status==='PASS'||status==='CLOSED') return '<span class="icon PASS">&#10003;</span>';
  if(status==='FAIL'||status==='BLOCKED') return '<span class="icon FAIL">&#10007;</span>';
  if(status==='RUNNING'||status==='RETRY') return '<span class="icon RUNNING">&#9654;</span>';
  return '<span class="icon NOT_STARTED">&#9675;</span>';
}
function val(id){ let el=document.getElementById(id); return el? el.value : ''; }

// "Just transitioned" banner (2026-09-01, runtime-progress-visibility pass):
// RULING -- always visible rather than a time-limited flash. A flash that
// auto-hides after N seconds is invisible to a viewer who was not staring at
// the tab the instant it fired (the exact "silent 3s poll, no distinct
// signal" gap this feature exists to close) and reintroduces the very
// failure mode it is meant to fix the moment the timer expires. An
// always-visible "Last transition: <stage> -> <status> at <time>" line is
// simpler to implement, impossible to miss on any page load/refresh, and
// never silently reverts to looking like nothing happened -- documented per
// the task's own "your call, document the ruling" allowance.
function renderLastTransitionBanner(lastTransition){
  let el = document.getElementById('lastTransitionBanner');
  let textEl = document.getElementById('lastTransitionText');
  if(!lastTransition || !lastTransition.stage){
    el.className = 'transitionBanner status-none';
    textEl.textContent = 'no stage has completed yet this run';
    return;
  }
  let status = lastTransition.status || '-';
  el.className = 'transitionBanner status-' + status;
  let when = lastTransition.at ? new Date(lastTransition.at).toLocaleString() : '(unknown time)';
  textEl.textContent = `${lastTransition.stage} → ${status} at ${when}`;
}

// Global Status Bar (Global Status Bar theme, sections 414-421/428). Reads
// GET /api/status -- harness_status.HarnessStatusService(root).serve()'s own
// real HarnessStatusIR snapshot -- never a second, dashboard-local
// aggregation of harness state. worst-wins section fold below mirrors
// harness_status_ir.worst_status()'s own severity order so this bar's
// per-section pill can never disagree with what that module would compute
// over the identical fields.
let _statusBarData = null;
let _statusBarLayout = 'standard'; // compact|standard|expanded, cycled by cycleStatusBarLayout()
const SB_SEVERITY_ORDER = ['FAILED','BLOCKED','HUMAN_GATE','STALE','UNKNOWN','RUNNING','VERIFYING',
  'RETRY_WAIT','BUDGET_EXHAUSTED','OSCILLATING','PLATEAU','CONVERGING','WAITING','IDLE','CANCELLED',
  'PARTIAL','READY','SIGNOFF_READY'];
function sbWorst(statuses){
  let ranked = (statuses||[]).filter(st=>st && st!=='NOT_APPLICABLE');
  if(!ranked.length) return 'UNKNOWN';
  ranked.sort((a,b)=>{
    let ia = SB_SEVERITY_ORDER.indexOf(a); if(ia<0) ia = SB_SEVERITY_ORDER.indexOf('UNKNOWN');
    let ib = SB_SEVERITY_ORDER.indexOf(b); if(ib<0) ib = SB_SEVERITY_ORDER.indexOf('UNKNOWN');
    return ia - ib;
  });
  return ranked[0];
}
function sbPillHtml(status){
  let st = status || 'UNKNOWN';
  return `<span class="sbPill status-${st}">${st}</span>`;
}
async function loadGlobalStatusBar(){
  try{
    _statusBarData = await (await fetch('/api/status')).json();
  } catch(e){
    _statusBarData = {available:false, status:null, error:{reason:'FETCH_FAILED', detail:{message:String(e)}}};
  }
  renderGlobalStatusBar();
}
// P2-3: push-driven status bar refresh, ADDITIVE on top of the existing
// setInterval(load,3000) poll loop below -- that loop is left completely
// intact as the working fallback it already is. This subscribes to the
// already-real GET /api/events/stream SSE route (live_event_model.py's
// eleven-name GUI_* vocabulary) and calls loadGlobalStatusBar() whenever a
// status-bar-relevant event arrives, so a refresh can happen the instant a
// real event is emitted rather than waiting for the next poll tick. An SSE
// connection can drop (network blip, server restart, browser throttling a
// background tab) -- EventSource's own built-in auto-reconnect handles
// that, and the poll loop keeps refreshing regardless either way, so
// losing the SSE connection never stops status-bar updates, it only
// removes this extra push-driven speed-up on top of them.
const SB_SSE_RELEVANT_EVENTS = ['GUI_STAGE_STATUS_CHANGED','GUI_STAGE_TRANSITIONED',
  'GUI_GATE_VERDICT_RECORDED','GUI_HUMAN_GATE_OPENED','GUI_QUESTION_QUEUE_UPDATED',
  'GUI_APPROVAL_RECORDED','GUI_LSF_JOB_STATUS_CHANGED','GUI_WAIVER_STATUS_CHANGED',
  'GUI_CONTROL_COMMAND_EXECUTED'];
function initGlobalStatusBarSSE(){
  try{
    if(typeof EventSource === 'undefined') return;  // unsupported browser -- poll loop still works
    let es = new EventSource('/api/events/stream');
    es.onmessage = function(ev){
      try{
        let data = JSON.parse(ev.data);
        if(data && SB_SSE_RELEVANT_EVENTS.indexOf(data.event) !== -1){
          loadGlobalStatusBar();
        }
      } catch(e){ /* malformed/heartbeat frame -- ignore, the poll loop is still the backstop */ }
    };
    es.onerror = function(){ /* EventSource auto-reconnects on its own; poll loop covers the gap */ };
  } catch(e){ /* SSE unavailable/blocked in this environment -- poll loop remains fully functional */ }
}
function cycleStatusBarLayout(){
  let order = ['compact','standard','expanded'];
  let i = order.indexOf(_statusBarLayout);
  _statusBarLayout = order[(i+1) % order.length];
  document.getElementById('sbLayoutBtn').textContent =
    _statusBarLayout.charAt(0).toUpperCase() + _statusBarLayout.slice(1);
  document.getElementById('globalStatusBar').className = 'statusBar mode-' + _statusBarLayout;
  // expanded mode keeps the detail drawer open by default; compact/standard
  // leave the drawer's own open/closed state exactly as the user last set it.
  if(_statusBarLayout === 'expanded'){
    document.getElementById('statusBarDrawer').style.display = '';
    renderStatusBarDrawer();
  }
}
function toggleStatusBarDrawer(){
  let d = document.getElementById('statusBarDrawer');
  d.style.display = (d.style.display === 'none') ? '' : 'none';
  if(d.style.display !== 'none') renderStatusBarDrawer();
}
function renderGlobalStatusBar(){
  let r = _statusBarData;
  if(!r || !r.available || !r.status){
    document.getElementById('sbIdentity').textContent = '(status unavailable)';
    document.getElementById('sbHarness').outerHTML = sbPillHtml('UNKNOWN').replace('sbPill','sbPill" id="sbHarness');
    document.getElementById('sbActivity').textContent = '-';
    document.getElementById('sbExecution').textContent = '-';
    document.getElementById('sbClosure').outerHTML = sbPillHtml('UNKNOWN').replace('sbPill','sbPill" id="sbClosure');
    document.getElementById('sbBlockers').textContent = '-';
    if(document.getElementById('statusBarDrawer').style.display !== 'none') renderStatusBarDrawer();
    return;
  }
  // NOTE ON SHAPE: harness_status.HarnessStatusService.serve() (this
  // batch's own real service -- see _read_harness_status_state()) returns
  // HarnessStatusIR.to_dict()'s FLAT shape: every status-bearing leaf is
  // already a plain status string (e.g. s.harness.state === "UNKNOWN"),
  // and every other leaf is a plain value/list/null -- never a nested
  // {status,value,fact_source,detail} record. This bar reads that flat
  // shape directly rather than assuming the differently-shaped
  // StatusField/EvidenceField dataclass harness_status_ir.py's own,
  // separate schema module defines (checked against the real endpoint's
  // real output before writing this).
  let s = r.status;
  let idf = (s.identity && (s.identity.project_name || s.identity.project_id)) || null;
  document.getElementById('sbIdentity').textContent = (idf != null) ? idf : '(no project id)';
  document.getElementById('sbHarness').outerHTML =
    sbPillHtml(s.harness && s.harness.state).replace('sbPill','sbPill" id="sbHarness');
  let wf = s.workflow || {};
  let activity = wf.current_node || wf.current_operation || wf.current_agent || '-';
  document.getElementById('sbActivity').textContent = activity;
  let ex = s.execution || {};
  let g = v => (v != null) ? v : '-';
  document.getElementById('sbExecution').textContent =
    `run:${g(ex.running_jobs)} pass:${g(ex.passed_jobs)} fail:${g(ex.failed_jobs)}`;
  let closureStatuses = Object.values(s.closure || {});
  document.getElementById('sbClosure').outerHTML =
    sbPillHtml(sbWorst(closureStatuses)).replace('sbPill','sbPill" id="sbClosure');
  let bl = s.blockers || {};
  document.getElementById('sbBlockers').textContent =
    `fail:${g(bl.critical_failures)} unk:${g(bl.critical_unknown)} gate:${g(bl.human_gates)}`;
  if(document.getElementById('statusBarDrawer').style.display !== 'none') renderStatusBarDrawer();
}
// Values reported bad enough to highlight in the drawer -- the harness's
// own HarnessStatus vocabulary (harness_status_ir.py section 406) members
// that mean "not clean", never guessed from an arbitrary string.
const SB_BAD_STATUS_TOKENS = new Set(['BLOCKED','FAILED','UNKNOWN','STALE','HUMAN_GATE',
  'BUDGET_EXHAUSTED','OSCILLATING']);
function renderStatusBarDrawer(){
  let d = document.getElementById('statusBarDrawer');
  let r = _statusBarData;
  if(!r || !r.available || !r.status){
    let err = r && r.error ? (r.error.reason + (r.error.detail ? ': '+JSON.stringify(r.error.detail) : '')) : 'no status snapshot available yet';
    d.innerHTML = `<div class="note err">${err}</div>`;
    return;
  }
  let s = r.status;
  let sections = ['identity','baseline','harness','workflow','execution','closure',
    'integration','blockers','resources','freshness','evidence'];
  let sectionsHtml = sections.map(sec=>{
    let obj = s[sec] || {};
    let rows = Object.keys(obj).map(k=>{
      let v = obj[k];
      let display = (v === null || v === undefined) ? '(absent)'
        : (typeof v === 'object') ? JSON.stringify(v)
        : String(v);
      let cls = SB_BAD_STATUS_TOKENS.has(display) ? 'err' : '';
      return `<div class="${cls}"><b>${k}</b>: ${display}</div>`;
    }).join('');
    return `<div class="statusBarDrawerSection"><h4>${sec}</h4>${rows}</div>`;
  }).join('');
  // s.unknowns (top-level, outside the eleven sections) names every field
  // the aggregator could not resolve and WHY -- real, citable evidence in
  // its own right (see harness_status.py's own GlobalStateAggregator), so
  // the drawer shows it as one more section rather than silently dropping it.
  let unknowns = s.unknowns || [];
  let unknownsHtml = `<div class="statusBarDrawerSection"><h4>unknowns (${unknowns.length})</h4>` +
    (unknowns.length
      ? unknowns.map(u=>`<div class="err"><b>${u.field}</b>: ${u.reason}</div>`).join('')
      : '<div>(none)</div>') + '</div>';
  d.innerHTML = sectionsHtml + unknownsHtml;
}

// Stage completion percent + entry/exit evidence checklist rendering
// (2026-09-01, runtime-progress-visibility pass): control_plane.
// describe_stage() (current_stage_detail/active_stages_detail below) always
// carried stage_completion_percent/gates_passed/gates_total/entry_checklist/
// exit_checklist as real data, but this card only ever dumped the whole
// dict as a JSON blob -- a human had to read raw JSON to notice a gate was
// missing or which single checklist item still needs to be supplied.
// checklistBlock() renders ONE checklist (entry or exit) as a real progress
// bar (reusing the existing .bar/.bar>div classes) plus one line per item,
// a missing item rendered bold+red (existing .err class) via the same
// icon() checkmark/x-mark convention the Graph card already uses for node
// status, with an explicit "still needs to be supplied" line naming exactly
// which item_id(s) are missing.
function checklistBlock(title, cl){
  if(!cl){
    return `<div style="margin-top:6px"><b>${title}:</b> <span class="note">not run yet this attempt -- no telemetry recorded</span></div>`;
  }
  let total = cl.total_count||0, present = cl.present_count||0;
  let pct = cl.completeness_percent!=null ? cl.completeness_percent : 100;
  let items = cl.items||[];
  let rows = items.length ? items.map(it=>{
    let desc = it.description ? ' - '+it.description : '';
    return it.present
      ? `<div>${icon('PASS')} ${it.item_id}${desc}</div>`
      : `<div class="err">${icon('FAIL')} <b>${it.item_id}</b>${desc}</div>`;
  }).join('') : '<div class="note">(no items declared for this stage)</div>';
  let missing = cl.missing_item_ids||[];
  let missingNote = missing.length
    ? `<div class="err" style="margin-top:4px">Still needs to be supplied: <b>${missing.join(', ')}</b></div>`
    : '';
  return `<div style="margin-top:6px"><b>${title}</b> -- ${present}/${total} present (${pct}%)
    <div class="bar" style="margin-top:4px"><div style="width:${pct}%"></div></div>
    ${rows}${missingNote}</div>`;
}
// Evidence-provenance caveat block (2026-09-06, TH-9). Six stage gates make
// claims about dynamic system BEHAVIOUR -- deadlock/livelock freedom, port
// starvation, fairness/QoS, interrupt latency, scoreboard liveness -- from
// numbers the agent typed, and their scripts only check the shape of those
// numbers. control_plane.describe_stage() now carries
// evidence_provenance.summarize_evidence_blocks() for exactly those gates, so
// this card can no longer present a self-attested "deadlock-free" identically
// to a tool-derived one. Rendered with the existing .err class (the same
// bold+red treatment a missing checklist item gets) precisely so it cannot be
// skimmed past. An empty/absent summary renders nothing -- a stage carrying
// none of these six gates has no such claim to caveat.
function provenanceBlock(p){
  if(!p || !(p.entries||[]).length) return '';
  let rows = p.entries.map(e=>{
    let declared = e.evidence_provenance || 'UNDECLARED';
    return e.independently_derived
      ? `<div>${icon('PASS')} <code>${e.gate_id}</code> [${declared}] -- ${e.claim}</div>`
      : `<div class="err">${icon('FAIL')} <b><code>${e.gate_id}</code> [${declared}]</b> -- ${e.claim}</div>`;
  }).join('');
  let banner = p.has_self_attested_claims
    ? `<div class="err" style="margin-top:4px"><b>${p.caveat}</b></div>`
    : '';
  return `<div style="margin-top:8px"><b>Evidence provenance (headline behaviour claims)</b>
    ${rows}${banner}</div>`;
}
function stageWhyHTML(d){
  if(!d) return '(no current stage)';
  let raw = `stage: ${d.stage}\nstatus: ${d.status}\nattempts: ${d.attempts}\nblocking_reason: ${d.blocking_reason||'(none)'}\ngate_verdict: ${d.gate_verdict}\ngate_reasons: ${JSON.stringify(d.gate_reasons)}\nhuman_correction: ${JSON.stringify(d.human_correction)}\nhuman_approval: ${JSON.stringify(d.human_approval)}\ntakeover: ${JSON.stringify(d.takeover)}`;
  let pct = d.stage_completion_percent!=null ? d.stage_completion_percent : 0;
  let gp = d.gates_passed!=null ? d.gates_passed : '-', gt = d.gates_total!=null ? d.gates_total : '-';
  return `<pre style="white-space:pre-wrap;font-size:12px;background:#f7f9fc;border:1px solid #e3e9f2;border-radius:6px;padding:8px;margin:0">${raw}</pre>`
    + `<div style="margin-top:8px"><b>Stage completion:</b> ${pct}% (${gp}/${gt} gates passed)
       <div class="bar" style="margin-top:4px"><div style="width:${pct}%"></div></div>
       ${d.stage_completion_note ? `<div class="note" style="margin-top:2px">${d.stage_completion_note}</div>` : ''}</div>`
    + provenanceBlock(d.evidence_provenance)
    + checklistBlock('Entry checklist (evidence required before this stage runs)', d.entry_checklist)
    + checklistBlock('Exit checklist (evidence this stage should have produced)', d.exit_checklist);
}

// Protocol tiles (Protocols card): a real click target wiring straight into
// the exact field POST /api/start already reads for scope -- doStart() below
// posts {goal: val('goalInput'), ...}, so filling #goalInput here is not a
// new, uncomsumed field, it is the one the backend already consumes.
function selectProtocol(el, name){
  document.getElementById('goalInput').value = 'verify ' + name;
  document.querySelectorAll('#protocoltiles .protoTile').forEach(t=>t.classList.remove('selected'));
  if(el) el.classList.add('selected');
}

// GUI-19 session token. The server NEVER embeds it in this page -- it
// arrives once, as ?token=... on the URL the dashboard printed at startup.
// It is moved into sessionStorage (per-tab, gone when the tab closes) and
// stripped from the address bar immediately, so it does not sit in browser
// history on every later navigation. A tab opened without it can still READ
// everything (GET is not gated); every mutating action returns 403 with the
// banner below telling the operator where the real token is.
const DV_TOKEN_HEADER = 'X-DV-Harness-Token';
function _captureToken(){
  try{
    let u = new URL(window.location.href);
    let t = u.searchParams.get('token');
    if(t){
      sessionStorage.setItem('dvHarnessToken', t);
      u.searchParams.delete('token');
      history.replaceState(null, '', u.pathname + (u.search||'') + (u.hash||''));
    }
  }catch(e){ /* sessionStorage blocked / non-URL context -- fall through to no token */ }
}
function _token(){
  try { return sessionStorage.getItem('dvHarnessToken') || ''; } catch(e) { return ''; }
}
function _showAuthBanner(data){
  let el = document.getElementById('authBanner');
  if(!el) return;
  el.textContent = 'ACCESS DENIED (' + (data.reason||'AUTH_REQUIRED') + '): ' + (data.message||'');
  el.style.display = 'block';
}
_captureToken();

async function postJSON(url, body){
  let resp, text, data;
  try{
    let headers = {'Content-Type':'application/json'};
    let t = _token();
    if(t) headers[DV_TOKEN_HEADER] = t;
    resp = await fetch(url, {method:'POST', headers: headers, body: JSON.stringify(body||{})});
    text = await resp.text();
    try { data = JSON.parse(text); } catch(e) { data = {raw:text}; }
    // PC-6: a ROLE refusal is shown in the same banner. An authenticated
    // VIEWER whose Approve click silently did nothing would read as a broken
    // page; the banner tells them which role the action needs.
    if(resp.status === 403 && data && (data.error === 'AUTH_REQUIRED' || data.error === 'ROLE_NOT_PERMITTED')) _showAuthBanner(data);
  } catch(e) {
    data = {error:'NETWORK_ERROR', message:String(e)};
    resp = {ok:false};
  }
  return {ok: !!(resp && resp.ok), data};
}
function showIn(elId, ok, data){
  let el = document.getElementById(elId);
  el.textContent = JSON.stringify(data, null, 2);
  el.className = ok ? 'ok' : 'err';
}

async function doSetup(){
  let r = await postJSON('/api/setup', {db_path: val('dbPathInput'), working_path: val('workingPathInput')});
  showIn('setupResult', r.ok, r.data);
  await load();
}
async function doStart(loop){
  let r = await postJSON('/api/start', {goal: val('goalInput'), loop: loop});
  showIn('runResult', r.ok, r.data);
  await load();
}
async function doControl(command, fields){
  let body = Object.assign({command: command}, fields);
  let r = await postJSON('/api/control', body);
  showIn('controlResult', r.ok, r.data);
  await load();
}
async function doCosign(){
  let raw = val('cosignValue');
  let value;
  try { value = JSON.parse(raw); } catch(e) { value = raw; }
  let body = {command:'COSIGN', stage: val('cosignStage'), field_path: val('cosignFieldPath'),
              value: value, reviewer_id: val('cosignReviewer'), reviewer_confidence: val('cosignConfidence')};
  let r = await postJSON('/api/control', body);
  showIn('cosignResult', r.ok, r.data);
  await load();
}
function _b64FromDataUrl(dataUrl){
  let idx = dataUrl.indexOf(',');
  return idx>=0 ? dataUrl.slice(idx+1) : dataUrl;
}
function _readFileAsB64(file){
  return new Promise((resolve,reject)=>{
    let reader = new FileReader();
    reader.onload = ()=>resolve(_b64FromDataUrl(reader.result));
    reader.onerror = ()=>reject(reader.error || new Error('file read failed'));
    reader.readAsDataURL(file);
  });
}
async function doUpload(category){
  let input = document.getElementById('uploadFile_'+category);
  let file = input && input.files && input.files[0];
  if(!file){
    showIn('uploadResult', false, {error:'NO_FILE', message:'choose a file for '+category+' first'});
    return;
  }
  let content_b64;
  try { content_b64 = await _readFileAsB64(file); }
  catch(e){ showIn('uploadResult', false, {error:'READ_ERROR', message:String(e)}); return; }
  let r = await postJSON('/api/upload', {category: category, filename: file.name, content_b64: content_b64});
  showIn('uploadResult', r.ok, r.data);
  await load();
}
async function doSignoffExport(){
  let outDir = val('signoffExportOutDir');
  let body = {};
  if(outDir) body.out_dir = outDir;
  let r = await postJSON('/api/signoff-export', body);
  showIn('signoffExportResult', r.ok, r.data);
  await load();
}
async function doWaiverSubmit(){
  // A Waiver ID present means the human is recording a real section 237
  // waiver -- server-side waiver_store.record_waiver() then validates every
  // field. Absent, this posts the original 4-field record unchanged, so an
  // existing caller/bookmark is never broken.
  let body;
  if(val('waiverId')){
    let reqIds = val('waiverRequirementIds').split(',').map(s=>s.trim()).filter(s=>s);
    // No gate_id: a section 237 record applies to all three waiver gates
    // (they check the same record from three angles). The Gate selector above
    // belongs to the legacy 4-field shape.
    body = {waiver_id: val('waiverId'), item: val('waiverItemId'),
            reason: val('waiverReason'), evidence: val('waiverEvidence'),
            approver: val('waiverApprover'), risk: val('waiverRisk'),
            created_at: new Date().toISOString(),
            scope: {requirement_ids: reqIds, subsystem: val('waiverSubsystem'),
                    spec_revision: val('waiverSpecRevision'),
                    design_evidence_hash: val('waiverDesignEvidenceHash'),
                    approval_id: val('waiverApprovalId'),
                    scope_hash: val('waiverScopeHash'),
                    applied_requirement_ids: reqIds},
            affected_version: {spec_revision: val('waiverSpecRevision'),
                               rtl_hash: val('waiverRtlHash'),
                               revision: val('waiverRevision')},
            revalidation_trigger: {}};
    // A blank field is a fact nobody recorded, never a trigger value of "" --
    // an empty trigger would compare unequal to every real revision and read
    // REVALIDATION_REQUIRED forever.
    for(const [k,id] of [['spec_revision','waiverSpecRevision'],
                         ['rtl_hash','waiverRtlHash'],
                         ['revision','waiverRevision']]){
      if(val(id)){ body.revalidation_trigger[k] = val(id); }
    }
    if(val('waiverExpiresAt')){ body.expires_at = val('waiverExpiresAt'); }
  } else {
    body = {gate_id: val('waiverGateId'), item_id: val('waiverItemId'),
            approved: document.getElementById('waiverApproved').checked,
            evidence: val('waiverEvidence')};
  }
  let r = await postJSON('/api/waiver', body);
  showIn('waiverResult', r.ok, r.data);
}
async function doConfigToggle(){
  let checked = document.getElementById('cosignEnforceToggle').checked;
  let r = await postJSON('/api/config', {key:'require_dv_review_cosign', value: checked});
  showIn('controlResult', r.ok, r.data);
  await load();
}
async function loadAudit(){
  let limit = val('auditLimit') || '50';
  let a = await (await fetch('/api/audit?limit='+encodeURIComponent(limit))).json();
  document.getElementById('auditResult').textContent = JSON.stringify(a, null, 2);
}
async function loadStageProfile(){
  let a = await (await fetch('/api/stage-profile')).json();
  document.getElementById('stageProfileResult').textContent = a.report || '';
}

// GUI Action Audit Log. Computes nothing itself -- renders
// gui_audit_log.py's own real structured records verbatim (see
// _read_gui_audit_log_state()'s own comment). "Detail" shows the full
// before/after/evidence/approval/result for one record; nothing here is
// mutating -- there is no write action anywhere on this card.
let _guiAuditLogData = null;
async function loadGuiAuditLog(){
  let limit = document.getElementById('guiAuditLogLimit').value || '50';
  let action = document.getElementById('guiAuditLogAction').value || '';
  let qs = 'limit='+encodeURIComponent(limit) + (action ? ('&action='+encodeURIComponent(action)) : '');
  _guiAuditLogData = await (await fetch('/api/gui-audit-log?'+qs)).json();
  renderGuiAuditLog();
}
function showGuiAuditLogDetail(i){
  let r = ((_guiAuditLogData || {}).records || [])[i];
  if(!r) return;
  alert(JSON.stringify(r, null, 2));
}
function renderGuiAuditLog(){
  let r = _guiAuditLogData;
  if(!r) return;
  let recs = r.records || [];
  let ok = recs.filter(x=>(x.result||{}).status==='OK').length;
  let err = recs.filter(x=>(x.result||{}).status==='ERROR').length;
  document.getElementById('guiAuditLogTiles').innerHTML = [
    tile(recs.length, 'Records Shown'),
    tile(ok, 'OK'),
    tile(err, 'ERROR'),
    tile(recs.filter(x=>x.approval).length, 'Granted an Approval'),
  ].join('');
  document.getElementById('guiAuditLogBody').innerHTML = recs.map((x,i)=>{
    let res = x.result || {};
    return `<tr style="border-bottom:1px solid #edf1f5">`+
      `<td style="padding:4px">${x.when||'-'}</td>`+
      `<td style="padding:4px"><code>${x.action||'-'}</code></td>`+
      `<td style="padding:4px">${x.who||'-'}</td>`+
      `<td style="padding:4px" class="${res.status==='ERROR'?'err':''}">${res.status||'-'}</td>`+
      `<td style="padding:4px">${x.approval?'yes':'-'}</td>`+
      `<td style="padding:4px"><button onclick="showGuiAuditLogDetail(${i})">Detail</button></td>`+
      `</tr>`;
  }).join('') || '<tr><td style="padding:4px" colspan="6">No structured GUI audit records found.</td></tr>';
}
// Human Gate Center. Computes nothing itself -- renders
// gui_action_safety.py's own real declarations plus real control.json
// approval status verbatim (see _read_human_gate_center_state()'s own
// comment). Approving happens ONLY through the pre-existing Control Plane
// card's Approve button/doControl('APPROVE',...) call above; this card's own
// "Approve this" link just pre-fills that existing <select id="approveStage">
// and scrolls to it -- it never posts anything itself.
let _humanGateApprovalOnlyStagesAdded = false;
function _addApprovalOnlyStageOptions(stages){
  // The pre-existing #approveStage <select> (Control Plane card) is only
  // ever populated from real graph node ids (fillStageSelects(), fed by
  // GET /api/graph) -- so the three fixed commands.APPROVAL_ONLY_STAGES keys
  // (RESEARCH_CAPABILITY_EVOLUTION / CHANGE_BLAST_RADIUS /
  // BOUNDED_SELF_HEALING), which ControlPlane.approve() already legally
  // accepts today, were never actually selectable from this GUI. Appended
  // once, additively -- never replaces the graph-node options
  // fillStageSelects() already put there.
  if(_humanGateApprovalOnlyStagesAdded) return;
  let sel = document.getElementById('approveStage');
  if(!sel) return;
  let existing = new Set(Array.from(sel.options).map(o=>o.value));
  (stages||[]).forEach(s=>{
    if(!existing.has(s)){
      let opt = document.createElement('option');
      opt.value = s; opt.textContent = s;
      sel.appendChild(opt);
    }
  });
  _humanGateApprovalOnlyStagesAdded = true;
}
function focusApproveStage(stage){
  let sel = document.getElementById('approveStage');
  if(sel){ sel.value = stage; sel.scrollIntoView({behavior:'smooth', block:'center'}); sel.focus(); }
}
let _humanGateData = null;
async function loadHumanGateCenter(){
  _humanGateData = await (await fetch('/api/human-gate-center')).json();
  renderHumanGateCenter();
}
function renderHumanGateCenter(){
  let r = _humanGateData;
  if(!r) return;
  _addApprovalOnlyStageOptions(r.approval_only_stages);
  let decls = r.declarations || [];
  let stages = r.governance_stages || [];
  let approvedCount = stages.filter(s=>s.approved).length;
  document.getElementById('humanGateCenterTiles').innerHTML = [
    tile((r.categories||[]).length, 'Categories'),
    tile(decls.length, 'Declared Actions'),
    tile(stages.length, 'Governance Stages Tracked'),
    tile(approvedCount, 'Currently Approved'),
    tile(stages.length - approvedCount, 'Pending (No Approval On File)'),
    tile(decls.filter(d=>d.reversible).length, 'Reversible Actions'),
  ].join('');
  document.getElementById('humanGateStagesBody').innerHTML = stages.map(s=>{
    let a = s.approval || {};
    return `<tr style="border-bottom:1px solid #edf1f5">`+
      `<td style="padding:4px"><code>${s.stage}</code>${s.is_current_stage?' <span class="note" style="display:inline">(current stage)</span>':''}</td>`+
      `<td style="padding:4px" class="${s.approved?'':'err'}">${s.approved?'APPROVED':'PENDING -- no approval on file'}</td>`+
      `<td style="padding:4px">${a.reviewer_id||'-'}</td>`+
      `<td style="padding:4px">${a.reviewer_confidence||'-'}</td>`+
      `<td style="padding:4px">${a.approved_at||'-'}</td>`+
      `<td style="padding:4px">${a.note||'-'}</td>`+
      `<td style="padding:4px">${s.history_count||0}</td>`+
      `<td style="padding:4px"><button onclick="focusApproveStage('${s.stage}')">${s.approved?'Re-approve':'Approve this'}</button></td>`+
      `</tr>`;
  }).join('') || '<tr><td style="padding:4px" colspan="8">No governance stages tracked yet (no current stage, no APPROVAL_ONLY_STAGES).</td></tr>';
  document.getElementById('humanGateDeclarationsBody').innerHTML = decls.map(d=>{
    return `<tr style="border-bottom:1px solid #edf1f5">`+
      `<td style="padding:4px"><code>${d.action_id}</code></td>`+
      `<td style="padding:4px">${d.category}</td>`+
      `<td style="padding:4px">${d.required_role}</td>`+
      `<td style="padding:4px">${d.impact}</td>`+
      `<td style="padding:4px">${d.reversible?'yes':'no'}</td>`+
      `<td style="padding:4px">${d.rollback_plan_kind}</td>`+
      `<td style="padding:4px;max-width:360px">${d.scope}</td>`+
      `<td style="padding:4px;max-width:280px" class="note">${d.note||''}</td>`+
      `</tr>`;
  }).join('');
}
let _jobsById = {};
async function loadJobs(){
  let jobs = await (await fetch('/api/lsf/jobs')).json();
  _jobsById = {};
  let rows = jobs.map(j=>{
    _jobsById[j.job_id] = j;
    let dv = j.dv_analysis_status || j.sim_status || '-';
    return `<tr style="cursor:pointer;border-bottom:1px solid #edf1f5" onclick="showJobDetail('${j.job_id}')">`+
      `<td style="padding:4px">${j.job_id!=null?j.job_id:'-'}</td><td style="padding:4px">${j.pattern||'-'}</td>`+
      `<td style="padding:4px">${j.lsf_status||'-'}</td><td style="padding:4px">${dv}</td>`+
      `<td style="padding:4px">${j.uvm_error_count!=null?j.uvm_error_count:'-'}</td>`+
      `<td style="padding:4px">${j.uvm_fatal_count!=null?j.uvm_fatal_count:'-'}</td></tr>`;
  }).join('');
  document.getElementById('jobsTableBody').innerHTML = rows || '<tr><td style="padding:4px" colspan="6">No jobs yet.</td></tr>';
}
function showJobDetail(jobId){
  let el = document.getElementById('jobDetail');
  el.style.display = '';
  el.textContent = JSON.stringify(_jobsById[jobId] || {}, null, 2);
}

async function loadSelfAudit(){
  let smoke = document.getElementById('selfAuditSmoke').checked;
  let a = await (await fetch('/api/self-audit'+(smoke?'?smoke=1':''))).json();
  let s = a.summary || {};
  document.getElementById('selfAuditTiles').innerHTML=[
    tile(s.total||0,'Total'), tile(s.pass||0,'Pass'), tile(s.fail||0,'Fail'),
    tile(s.no_source_data||0,'No Source Data'), tile(s.tool_missing||0,'Tool Missing'),
    tile(s.smoke_pass||0,'Smoke Pass'), tile(s.smoke_fail||0,'Smoke Fail'),
  ].join('');
  let rows = (a.gates||[]).map(g=>
    `<tr style="border-bottom:1px solid #edf1f5"><td style="padding:4px"><code>${g.gate_id}</code></td>`+
    `<td style="padding:4px" class="${g.status}">${g.status}</td><td style="padding:4px">${g.mode}</td>`+
    `<td style="padding:4px">${JSON.stringify(g.detail)}</td></tr>`
  ).join('');
  document.getElementById('selfAuditTableBody').innerHTML = rows || '<tr><td style="padding:4px" colspan="4">No results.</td></tr>';
}

async function loadCoverageAnalysis(){
  let r = await (await fetch('/api/coverage')).json();
  let tbody = document.getElementById('coverageHolesTableBody');
  let note = document.getElementById('coverageTrendNote');
  let chart = document.getElementById('coverageTrendChart');
  if(!r.available){
    tbody.innerHTML = '<tr><td style="padding:4px" colspan="4">No coverage summary yet (looked for '+r.summary_path+').</td></tr>';
    note.textContent = '';
    chart.innerHTML = '';
    return;
  }
  if(r.error){
    tbody.innerHTML = '<tr><td style="padding:4px" colspan="4" class="err">'+r.error.reason+': '+JSON.stringify(r.error.detail)+'</td></tr>';
    note.textContent = '';
    chart.innerHTML = '';
    return;
  }
  let rows = (r.holes||[]).map(h=>
    `<tr style="border-bottom:1px solid #edf1f5"><td style="padding:4px">${h.name}</td>`+
    `<td style="padding:4px">${h.percent}%</td><td style="padding:4px">${h.bins_hit}/${h.bins_total}</td>`+
    `<td style="padding:4px">${h.bins_missing}</td></tr>`
  ).join('');
  tbody.innerHTML = rows || '<tr><td style="padding:4px" colspan="4">No coverage holes -- 100% across all reported categories.</td></tr>';
  note.textContent = r.trend
    ? `Trend: ${r.trend.trend} (delta ${r.trend.delta.toFixed(1)}%, ${r.trend.first_percent}% -> ${r.trend.last_percent}%)`
    : 'Not enough history yet for a trend chart (need >= 2 timestamped samples in history.json).';
  chart.innerHTML = r.trend_svg || '';
}

// AMBA Fabric / VIP Bind / Scoreboard card (GUI-09). Fetch-once + filter
// client-side, same shape as the FSDB card above -- typing in the filter must
// not re-read the registry file on every keystroke.
let _ambaData = null;
async function loadAmbaFabric(){
  _ambaData = await (await fetch('/api/amba')).json();
  renderAmbaTable();
}
function renderAmbaTable(){
  let r = _ambaData;
  let tiles = document.getElementById('ambaTiles');
  let tbody = document.getElementById('ambaTableBody');
  let note = document.getElementById('ambaUnresolvedNote');
  if(!r) return;
  if(!r.available){
    tiles.innerHTML = tile('-','No AMBA port registry yet');
    tbody.innerHTML = '<tr><td style="padding:4px" colspan="10">No AMBA_PORT_REGISTRY yet (looked for '+r.registry_path+').</td></tr>';
    note.textContent = '';
    return;
  }
  if(r.error){
    tiles.innerHTML = tile('ERROR','AMBA_PORT_REGISTRY');
    tbody.innerHTML = '<tr><td style="padding:4px" colspan="10" class="err">'+r.error.reason+': '+JSON.stringify(r.error.detail)+'</td></tr>';
    note.textContent = '';
    return;
  }
  let s = r.summary || {}, rc = s.readiness_counts || {};
  tiles.innerHTML = [
    tile(s.fabric_port_count||0,'Fabric Ports'), tile(s.row_count||0,'Registry Rows'),
    tile(rc.READY||0,'Bind READY'), tile(rc.PARTIAL||0,'Bind PARTIAL'),
    tile(rc.BLOCKED||0,'Bind BLOCKED'), tile(rc.UNKNOWN||0,'Bind UNKNOWN'),
    tile(s.vip_planned||0,'VIP Planned'), tile(s.vip_not_planned||0,'No VIP Planned'),
    tile(s.scoreboard_channel_mapped||0,'Scoreboard Channel Mapped'),
    tile(s.traced_master_count||0,'Traced Masters'), tile(s.traced_slave_count||0,'Traced Slaves'),
    tile(s.unresolved_count||0,'Unresolved Endpoints')
  ].join('');
  let f = (val('ambaPortFilter')||'').toLowerCase();
  let all = r.rows||[];
  let rows = f ? all.filter(row=>[row.port_id,row.fabric_port,row.endpoint_hierarchy,row.vip_bind_hierarchy]
                                   .some(v=>String(v||'').toLowerCase().includes(f))) : all;
  tbody.innerHTML = rows.map(row=>{
    // The AMBA-15 widths and the row's citable source_evidence go on the row's
    // title rather than into ten more columns -- they are the drill-down a
    // reviewer wants on one specific port, not a scan-the-table fact.
    let hover = `clock: ${row.clock} | reset: ${row.reset} | address_width: ${row.address_width}`
      + ` | data_width: ${row.data_width} | id_width: ${row.id_width} | user_widths: ${row.user_widths}`
      + ` | evidence: ${(row.source_evidence||[]).join(' ; ')}`;
    return `<tr style="border-bottom:1px solid #edf1f5" title="${hover.replace(/"/g,'&quot;')}">`+
      `<td style="padding:4px"><code>${row.port_id}</code></td><td style="padding:4px">${row.protocol}</td>`+
      `<td style="padding:4px">${row.fabric_role}</td><td style="padding:4px">${row.endpoint_hierarchy}</td>`+
      `<td style="padding:4px">${row.vip_bind_hierarchy}</td><td style="padding:4px">${row.vip_mode}</td>`+
      `<td style="padding:4px">${row.scoreboard_channel}</td><td style="padding:4px">${row.trace_status}</td>`+
      `<td style="padding:4px" class="${row.readiness}">${row.readiness}</td>`+
      `<td style="padding:4px">${row.confidence}</td></tr>`;
  }).join('') || `<tr><td style="padding:4px" colspan="10">${all.length? 'No rows match the current filter.' : 'Registry file present but no fabric port was discovered.'}</td></tr>`;
  let unresolved = (r.endpoints && r.endpoints.unresolved) || [];
  note.innerHTML = unresolved.length
    ? 'Ports with no established endpoint (AMBA-14 never invents one): '
      + unresolved.map(u=>`<code>${u.port_id}</code> (${u.trace_status})`).join(', ')
    : 'Every registry row established a real transaction endpoint.';
}

// AMBA Fabric Connectivity Matrix card (dashboard_amba_connectivity_matrix_ui).
// Fetch-once + render, same shape as the AMBA-22 registry card above -- renders
// only amba_fabric_graph_ir.build_amba_fabric_graph()'s own real node/edge
// rows, never a dashboard-local re-derivation of node-kind legality or
// reconfigurable-claim grounding.
let _ambaConnectivityMatrixData = null;
async function loadAmbaConnectivityMatrix(){
  _ambaConnectivityMatrixData = await (await fetch('/api/amba-connectivity-matrix')).json();
  renderAmbaConnectivityMatrix();
}
function renderAmbaConnectivityMatrix(){
  let r = _ambaConnectivityMatrixData;
  let tiles = document.getElementById('ambaConnectivityMatrixTiles');
  let nodesBody = document.getElementById('ambaConnectivityMatrixNodesBody');
  let edgesBody = document.getElementById('ambaConnectivityMatrixEdgesBody');
  if(!r) return;
  if(!r.available){
    tiles.innerHTML = tile('-','No AMBA fabric graph yet');
    nodesBody.innerHTML = '<tr><td style="padding:4px" colspan="4">No fabric graph yet (looked for '+r.graph_path+').</td></tr>';
    edgesBody.innerHTML = '';
    return;
  }
  if(r.error){
    tiles.innerHTML = tile('ERROR','AMBA Fabric Graph');
    let msg = r.error.reason+': '+JSON.stringify(r.error.detail);
    nodesBody.innerHTML = '<tr><td style="padding:4px" colspan="4" class="err">'+msg+'</td></tr>';
    edgesBody.innerHTML = '';
    return;
  }
  let s = r.summary || {};
  tiles.innerHTML = [
    tile(s.node_count||0,'Nodes'), tile(s.edge_count||0,'Edges'),
    tile(s.reconfigurable_node_count||0,'Reconfigurable Nodes'),
  ].join('');
  nodesBody.innerHTML = (r.nodes||[]).map(n=>
    `<tr style="border-bottom:1px solid #edf1f5">`+
    `<td style="padding:4px"><code>${n.node_id}</code></td><td style="padding:4px">${n.kind}</td>`+
    `<td style="padding:4px">${n.reconfigurable?'yes':'no'}</td><td style="padding:4px">${n.evidence}</td></tr>`
  ).join('') || '<tr><td style="padding:4px" colspan="4">No nodes declared.</td></tr>';
  edgesBody.innerHTML = (r.edges||[]).map(e=>
    `<tr style="border-bottom:1px solid #edf1f5">`+
    `<td style="padding:4px"><code>${e.from}</code></td><td style="padding:4px"><code>${e.to}</code></td>`+
    `<td style="padding:4px">${e.evidence}</td></tr>`
  ).join('') || '<tr><td style="padding:4px" colspan="3">No edges declared.</td></tr>';
}

// AMBA Path Explorer card (dashboard_amba_path_explorer_ui). Loads the same
// document the connectivity-matrix card reads, populates a master/slave
// picker from amba_fabric_graph_ir.AMBAPathIR's own declared pairs, then
// fetches that one pair's real route(s) on selection -- never a
// dashboard-local re-derivation of route enumeration or graph consistency.
let _ambaPathExplorerPairs = null;
async function loadAmbaPathExplorer(){
  let r = await (await fetch('/api/amba-path-explorer')).json();
  _ambaPathExplorerPairs = r;
  let mSel = document.getElementById('ambaPathMaster');
  let sSel = document.getElementById('ambaPathSlave');
  let tiles = document.getElementById('ambaPathExplorerTiles');
  let body = document.getElementById('ambaPathExplorerBody');
  if(!r.available){
    tiles.innerHTML = tile('-','No AMBA fabric graph yet');
    body.innerHTML = '<tr><td style="padding:4px" colspan="5">No fabric graph yet (looked for '+r.graph_path+').</td></tr>';
    mSel.innerHTML = ''; sSel.innerHTML = '';
    return;
  }
  if(r.error){
    tiles.innerHTML = tile('ERROR','AMBA Path IR');
    body.innerHTML = '<tr><td style="padding:4px" colspan="5" class="err">'+r.error.reason+': '+JSON.stringify(r.error.detail)+'</td></tr>';
    mSel.innerHTML = ''; sSel.innerHTML = '';
    return;
  }
  let pairs = r.pairs||[];
  let masters = [...new Set(pairs.map(p=>p.master))];
  mSel.innerHTML = masters.map(m=>`<option value="${m}">${m}</option>`).join('') || '<option value="">(none declared)</option>';
  tiles.innerHTML = tile(pairs.length,'Declared (master, slave) Pairs');
  onAmbaPathMasterChange();
}
function onAmbaPathMasterChange(){
  let r = _ambaPathExplorerPairs;
  let sSel = document.getElementById('ambaPathSlave');
  let m = document.getElementById('ambaPathMaster').value;
  let pairs = (r && r.pairs) || [];
  let slaves = pairs.filter(p=>p.master===m).map(p=>p.slave);
  sSel.innerHTML = slaves.map(s=>`<option value="${s}">${s}</option>`).join('') || '<option value="">(none)</option>';
  loadAmbaPathExplorerRoutes();
}
async function loadAmbaPathExplorerRoutes(){
  let m = document.getElementById('ambaPathMaster').value;
  let s = document.getElementById('ambaPathSlave').value;
  let tiles = document.getElementById('ambaPathExplorerTiles');
  let body = document.getElementById('ambaPathExplorerBody');
  let pairCount = ((_ambaPathExplorerPairs && _ambaPathExplorerPairs.pairs) || []).length;
  if(!m || !s){
    tiles.innerHTML = tile(pairCount,'Declared (master, slave) Pairs');
    body.innerHTML = '<tr><td style="padding:4px" colspan="5">Pick a master and slave above.</td></tr>';
    return;
  }
  let r = await (await fetch('/api/amba-path-explorer?master='+encodeURIComponent(m)+'&slave='+encodeURIComponent(s))).json();
  if(r.error){
    body.innerHTML = '<tr><td style="padding:4px" colspan="5" class="err">'+r.error.reason+': '+JSON.stringify(r.error.detail)+'</td></tr>';
    return;
  }
  tiles.innerHTML = [tile(pairCount,'Declared Pairs'), tile((r.paths||[]).length,'Routes For '+m+' -> '+s)].join('');
  body.innerHTML = (r.paths||[]).map(p=>
    `<tr style="border-bottom:1px solid #edf1f5">`+
    `<td style="padding:4px"><code>${p.route_id}</code></td>`+
    `<td style="padding:4px">${(p.hops||[]).join(' -> ')||'(not declared)'}</td>`+
    `<td style="padding:4px" class="${p.consistency}">${p.consistency}</td>`+
    `<td style="padding:4px">${(p.findings||[]).join('; ')||'-'}</td>`+
    `<td style="padding:4px">${(p.evidence||[]).join('; ')}</td></tr>`
  ).join('') || `<tr><td style="padding:4px" colspan="5">No declared route for ${m} -> ${s}.</td></tr>`;
}

// AMBA Bottleneck Analysis card (dashboard_amba_bottleneck_analysis_ui).
// Fetch-once + render, same shape as the two AMBA cards above -- renders only
// amba_performance_classification.identify_bottleneck_candidate()'s own real
// Hypothesis->Evidence->Confidence->Gap->Next-Best-Action record, never a
// dashboard-local root-cause guess.
let _ambaBottleneckData = null;
async function loadAmbaBottleneck(){
  _ambaBottleneckData = await (await fetch('/api/amba-bottleneck')).json();
  renderAmbaBottleneck();
}
function renderAmbaBottleneck(){
  let r = _ambaBottleneckData;
  let tiles = document.getElementById('ambaBottleneckTiles');
  let body = document.getElementById('ambaBottleneckBody');
  let note = document.getElementById('ambaBottleneckRejectedNote');
  if(!r) return;
  if(!r.available){
    tiles.innerHTML = tile('-','No declared bottleneck candidates yet');
    body.innerHTML = '<tr><td style="padding:4px" colspan="5">No candidates file yet (looked for '+r.candidates_path+').</td></tr>';
    note.innerHTML = '';
    return;
  }
  if(r.error){
    tiles.innerHTML = tile('ERROR','Bottleneck Candidates');
    body.innerHTML = '<tr><td style="padding:4px" colspan="5" class="err">'+r.error.reason+': '+JSON.stringify(r.error.detail)+'</td></tr>';
    note.innerHTML = '';
    return;
  }
  let cands = r.candidates||[];
  let rejected = r.rejected||[];
  tiles.innerHTML = [tile(cands.length,'Bottleneck Candidates'), tile(rejected.length,'Rejected Declarations')].join('');
  body.innerHTML = cands.map(c=>
    `<tr style="border-bottom:1px solid #edf1f5">`+
    `<td style="padding:4px">${c.hypothesis}</td>`+
    `<td style="padding:4px"><ul style="margin:0;padding-left:16px">${(c.evidence||[]).map(e=>'<li>'+e+'</li>').join('')}</ul></td>`+
    `<td style="padding:4px"><b>${c.confidence}</b></td>`+
    `<td style="padding:4px">${c.gap}</td>`+
    `<td style="padding:4px">${c.next_best_action}</td></tr>`
  ).join('') || '<tr><td style="padding:4px" colspan="5">No bottleneck candidates declared.</td></tr>';
  note.innerHTML = rejected.length
    ? 'Rejected declarations (identify_bottleneck_candidate() never builds a bare label): '
      + rejected.map(x=>`<code>${x.id}</code> (${x.reason})`).join('; ')
    : '';
}

// Resource Orchestrator card (resource-orchestrator-no-dashboard-card gap-close).
// Fetch-once + render, same shape as the AMBA cards above -- renders only
// resource_orchestrator.orchestrate()'s own real ArbitrationPlan, never a
// dashboard-local arbitration decision.
let _resourceOrchestratorData = null;
async function loadResourceOrchestrator(){
  _resourceOrchestratorData = await (await fetch('/api/resource-orchestrator')).json();
  renderResourceOrchestrator();
}
function renderResourceOrchestrator(){
  let r = _resourceOrchestratorData;
  let tiles = document.getElementById('resourceOrchestratorTiles');
  let body = document.getElementById('resourceOrchestratorBody');
  let skippedNote = document.getElementById('resourceOrchestratorSkippedNote');
  let discNote = document.getElementById('resourceOrchestratorDisclosureNote');
  if(!r) return;
  if(!r.available){
    tiles.innerHTML = tile('-','No declared plan inputs yet');
    body.innerHTML = '<tr><td style="padding:4px" colspan="6">No inputs file yet (looked for '+r.inputs_path+'). Declare requests, or rely on the real cross-project registry.</td></tr>';
    skippedNote.innerHTML = '';
    discNote.innerHTML = '';
    return;
  }
  if(r.error){
    tiles.innerHTML = tile('ERROR','Resource Orchestrator');
    body.innerHTML = '<tr><td style="padding:4px" colspan="6" class="err">'+r.error.reason+': '+JSON.stringify(r.error.detail)+'</td></tr>';
    skippedNote.innerHTML = '';
    discNote.innerHTML = '';
    return;
  }
  let plan = r.plan;
  if(!plan){
    tiles.innerHTML = tile('-', r.note || 'No contenders');
    body.innerHTML = '<tr><td style="padding:4px" colspan="6">'+(r.note||'No contenders declared or found in the registry.')+'</td></tr>';
    skippedNote.innerHTML = '';
    discNote.innerHTML = '';
    return;
  }
  let cap = plan.capacity || {};
  tiles.innerHTML = [tile(plan.granted||0,'Granted'), tile(plan.queued||0,'Queued'),
    tile(plan.deferred||0,'Deferred'), tile(plan.slots_committed||0,'Slots Committed'),
    tile(cap.slots_available!=null ? cap.slots_available : 'unmeasured', 'Capacity (binding: '+(cap.binding_constraint||'none')+')')
  ].join('');
  let allocs = (plan.allocations||[]).slice().sort((a,b)=>(a.rank==null?9999:a.rank)-(b.rank==null?9999:b.rank));
  body.innerHTML = allocs.map(a=>{
    let cls = a.decision==='GRANTED' ? 'PASS' : (a.decision==='QUEUED' ? 'PARTIAL' : 'BLOCKED');
    return `<tr style="border-bottom:1px solid #edf1f5">`+
      `<td style="padding:4px">${a.rank==null?'-':a.rank}</td>`+
      `<td style="padding:4px">${a.project_id} / ${a.stage}</td>`+
      `<td style="padding:4px" class="${cls}"><b>${a.decision}</b></td>`+
      `<td style="padding:4px">${a.priority}</td>`+
      `<td style="padding:4px">${a.held_slots==null?'unknown':a.held_slots}</td>`+
      `<td style="padding:4px">${a.reason}</td></tr>`;
  }).join('') || '<tr><td style="padding:4px" colspan="6">No allocations.</td></tr>';
  let skipped = r.skipped||[];
  skippedNote.innerHTML = skipped.length
    ? 'Skipped (no readable current stage / graph): ' + skipped.map(s=>`<code>${s.project_id||s.root}</code> (${s.reason})`).join('; ')
    : '';
  discNote.innerHTML = plan.disclosure || '';
}

// AMBA Per-Port Performance Center (dashboard_amba_per_port_performance_center).
// Fetch-once + render, same shape as the AMBA cards above -- renders only
// amba_performance_calculator.aggregate_port_performance()'s own real
// PortPerformanceIR/PathPerformanceIR fields, honestly showing this module's
// own COMPUTED/UNKNOWN/NOT_APPLICABLE status per metric rather than a
// fabricated number.
let _ambaPerfData = null;
async function loadAmbaPerf(){
  _ambaPerfData = await (await fetch('/api/amba-performance')).json();
  renderAmbaPerf();
}
function _perfMetric(m){
  if(!m) return 'n/a';
  if(m.status !== 'COMPUTED') return `<b>${m.status}</b>${m.reason?' <span class="note" style="display:inline">('+m.reason+')</span>':''}`;
  let v = (typeof m.value === 'number') ? m.value.toPrecision(6) : m.value;
  return `${v}${m.unit?(' '+m.unit):''}`;
}
function _perfLatency(l){
  if(!l) return 'n/a';
  if(l.status !== 'COMPUTED') return `<b>${l.status}</b>${l.reason?' <span class="note" style="display:inline">('+l.reason+')</span>':''}`;
  let p = l.percentiles||{};
  return ['p50','p90','p95','p99'].map(k=>p[k]!=null?p[k].toPrecision(4):'-').join(' / ');
}
function _perfOutstanding(o){
  if(!o) return 'n/a';
  if(o.status !== 'COMPUTED') return `<b>${o.status}</b>${o.reason?' <span class="note" style="display:inline">('+o.reason+')</span>':''}`;
  return `avg ${o.average!=null?o.average.toPrecision(4):'-'}, peak ${o.peak!=null?o.peak:'-'}`;
}
function renderAmbaPerf(){
  let r = _ambaPerfData;
  let tiles = document.getElementById('ambaPerfPortTiles');
  let portBody = document.getElementById('ambaPerfPortBody');
  let pathBody = document.getElementById('ambaPerfPathBody');
  let note = document.getElementById('ambaPerfRejectedNote');
  if(!r) return;
  if(!r.available){
    tiles.innerHTML = tile('-','No declared performance samples yet');
    portBody.innerHTML = '<tr><td style="padding:4px" colspan="9">No samples file yet (looked for '+r.samples_path+').</td></tr>';
    pathBody.innerHTML = '<tr><td style="padding:4px" colspan="6">No samples file yet.</td></tr>';
    note.innerHTML = '';
    return;
  }
  if(r.error){
    tiles.innerHTML = tile('ERROR','Performance Samples');
    portBody.innerHTML = '<tr><td style="padding:4px" colspan="9" class="err">'+r.error.reason+': '+JSON.stringify(r.error.detail)+'</td></tr>';
    pathBody.innerHTML = '';
    note.innerHTML = '';
    return;
  }
  let ports = r.ports||[];
  let paths = r.paths||[];
  let rejected = r.rejected||[];
  tiles.innerHTML = [tile(ports.length,'Ports'), tile(paths.length,'Paths'), tile(rejected.length,'Rejected Declarations')].join('');
  portBody.innerHTML = ports.map(p=>
    `<tr style="border-bottom:1px solid #edf1f5">`+
    `<td style="padding:4px"><code>${p.port_id}</code></td>`+
    `<td style="padding:4px">${p.sample_count}</td>`+
    `<td style="padding:4px">${_perfMetric(p.bandwidth)}</td>`+
    `<td style="padding:4px">${_perfMetric(p.throughput)}</td>`+
    `<td style="padding:4px">${_perfLatency(p.latency_report)}</td>`+
    `<td style="padding:4px">${_perfOutstanding(p.outstanding)}</td>`+
    `<td style="padding:4px">${_perfMetric(p.stall_ratio)}</td>`+
    `<td style="padding:4px">${_perfMetric(p.utilization)}</td>`+
    `<td style="padding:4px">${_perfMetric(p.bandwidth_utilization)}</td></tr>`
  ).join('') || '<tr><td style="padding:4px" colspan="9">No ports declared.</td></tr>';
  pathBody.innerHTML = paths.map(p=>
    `<tr style="border-bottom:1px solid #edf1f5">`+
    `<td style="padding:4px"><code>${p.path_id}</code></td>`+
    `<td style="padding:4px">${p.source_port} -&gt; ${p.dest_port}</td>`+
    `<td style="padding:4px">${p.sample_count}</td>`+
    `<td style="padding:4px">${_perfMetric(p.bandwidth)}</td>`+
    `<td style="padding:4px">${_perfMetric(p.throughput)}</td>`+
    `<td style="padding:4px">${_perfLatency(p.latency_report)}</td></tr>`
  ).join('') || '<tr><td style="padding:4px" colspan="6">No paths declared.</td></tr>';
  note.innerHTML = rejected.length
    ? 'Rejected declarations (aggregate_port_performance() refused these -- never fabricated): '
      + rejected.map(x=>`<code>${x.kind}:${x.id}</code> (${x.reason})`).join('; ')
    : '';
}

// AMBA Performance Trend View (dashboard_amba_performance_trend_view).
// Fetch-once + render, same shape as the AMBA cards above -- renders only
// amba_performance_classification.compute_regression_delta()/detect_anomaly()'s
// own real results across a metric's own recorded periods, never a
// dashboard-local trend estimate. A metric with fewer than 2 recorded
// periods renders INCONCLUSIVE; one with none renders NOT_AVAILABLE --
// never a fabricated trend line.
let _ambaPerfTrendData = null;
async function loadAmbaPerfTrend(){
  _ambaPerfTrendData = await (await fetch('/api/amba-performance-trend')).json();
  renderAmbaPerfTrend();
}
function _trendStatusBadge(s){
  return s === 'AVAILABLE' ? '<b class="ok">AVAILABLE</b>' : `<b>${s}</b>`;
}
function _trendDeltaLine(d){
  let pct = (typeof d.percent_change === 'number') ? d.percent_change.toFixed(2)+'%' : 'n/a';
  return `${d.baseline_period_id} -&gt; ${d.current_period_id}: <b>${d.verdict}</b> (${pct})`
    + (d.reason ? ` <span class="note" style="display:inline">-- ${d.reason}</span>` : '');
}
function _trendAnomalyLine(a){
  let dev = (typeof a.deviation === 'number') ? a.deviation.toFixed(3) : 'n/a';
  return `${a.period_id}: <b>${a.status}</b> (deviation ${dev})`
    + (a.reason ? ` <span class="note" style="display:inline">-- ${a.reason}</span>` : '');
}
function renderAmbaPerfTrend(){
  let r = _ambaPerfTrendData;
  let tiles = document.getElementById('ambaPerfTrendTiles');
  let body = document.getElementById('ambaPerfTrendBody');
  let note = document.getElementById('ambaPerfTrendRejectedNote');
  if(!r) return;
  if(!r.available){
    tiles.innerHTML = tile('-','No declared performance-trend history yet');
    body.innerHTML = '<tr><td style="padding:4px" colspan="5">No trend file yet (looked for '+r.trend_path+').</td></tr>';
    note.innerHTML = '';
    return;
  }
  if(r.error){
    tiles.innerHTML = tile('ERROR','Performance Trend');
    body.innerHTML = '<tr><td style="padding:4px" colspan="5" class="err">'+r.error.reason+': '+JSON.stringify(r.error.detail)+'</td></tr>';
    note.innerHTML = '';
    return;
  }
  let metrics = r.metrics||[];
  let rejected = r.rejected||[];
  let avail = metrics.filter(m=>m.trend_status==='AVAILABLE').length;
  let inconclusive = metrics.filter(m=>m.trend_status==='INCONCLUSIVE').length;
  let notAvail = metrics.filter(m=>m.trend_status==='NOT_AVAILABLE').length;
  tiles.innerHTML = [
    tile(metrics.length,'Metrics'), tile(avail,'Trend Available'),
    tile(inconclusive,'Inconclusive'), tile(notAvail,'Not Available'),
    tile(rejected.length,'Rejected Declarations'),
  ].join('');
  body.innerHTML = metrics.map(m=>
    `<tr style="border-bottom:1px solid #edf1f5">`+
    `<td style="padding:4px"><code>${m.metric_name}</code></td>`+
    `<td style="padding:4px">${m.periods_recorded}</td>`+
    `<td style="padding:4px">${_trendStatusBadge(m.trend_status)}${m.trend_reason?' <span class="note" style="display:inline">('+m.trend_reason+')</span>':''}</td>`+
    `<td style="padding:4px"><ul style="margin:0;padding-left:16px">${(m.deltas||[]).map(d=>'<li>'+_trendDeltaLine(d)+'</li>').join('')||'<li class="note">none</li>'}</ul></td>`+
    `<td style="padding:4px"><ul style="margin:0;padding-left:16px">${(m.anomalies||[]).map(a=>'<li>'+_trendAnomalyLine(a)+'</li>').join('')||'<li class="note">none</li>'}</ul></td></tr>`
  ).join('') || '<tr><td style="padding:4px" colspan="5">No performance-trend metrics declared.</td></tr>';
  note.innerHTML = rejected.length
    ? 'Rejected declarations (compute_regression_delta()/detect_anomaly() refused these -- never fabricated): '
      + rejected.map(x=>`<code>${x.metric}${x.period?(':'+x.period):''}</code> (${x.reason})`).join('; ')
    : '';
}

// Research / Capability Evolution card (GUI-10). Same fetch-then-render shape
// as the AMBA card above; the three action buttons go through /api/control,
// never a research-specific POST endpoint.
let _researchData = null;
async function loadResearch(){
  _researchData = await (await fetch('/api/research')).json();
  renderResearchTable();
}
function renderResearchTable(){
  let r = _researchData;
  if(!r) return;
  let tiles = document.getElementById('researchTiles');
  let tbody = document.getElementById('researchTableBody');
  let note = document.getElementById('researchApprovalNote');
  let a = r.approval || {};
  // The gate's own state is rendered whether or not any candidate exists: "no
  // standing approval" is itself the fact a reviewer came here to check.
  note.innerHTML = 'Human Approval Gate <code>'+(a.stage||'')+'</code>: '
    + (a.approved
        ? '<b class="ok">APPROVAL STANDING</b> by '+(a.approval&&a.approval.reviewer_id)
          +' ('+(a.approval&&a.approval.reviewer_confidence)+') at '+(a.approval&&a.approval.approved_at)
          +' -- note: '+(a.approval&&a.approval.note||'')
        : '<b>no standing approval</b> -- nothing may transition to HUMAN_APPROVED until one exists')
    + '. Prior approvals archived: '+((a.history||[]).length)
    + '. Equivalent CLI: <code>'+(a.approve_command||'')+'</code>';
  if(r.error){
    tiles.innerHTML = tile('ERROR','Capability Evolution');
    tbody.innerHTML = '<tr><td style="padding:4px" colspan="8" class="err">'+r.error.reason+': '+JSON.stringify(r.error.detail)+'</td></tr>';
    return;
  }
  if(!r.available){
    tiles.innerHTML = tile(0,'Candidates');
    tbody.innerHTML = '<tr><td style="padding:4px" colspan="8">No CapabilityEvolutionCandidate filed yet on Blackboard topic <code>'+r.blackboard_topic+'</code>. A candidate is raised by the research route (<code>dv-harness research &lt;document&gt;</code>), never by this page.</td></tr>';
    return;
  }
  let c = r.counts || {}, bs = c.by_status || {}, br = c.by_recommendation || {};
  tiles.innerHTML = [tile(c.total||0,'Candidates')]
    .concat((r.recommendations||[]).filter(k=>br[k]).map(k=>tile(br[k],'Rec: '+k)))
    .concat((r.promotion_states||[]).filter(k=>bs[k]).map(k=>tile(bs[k],k)))
    .join('');
  tbody.innerHTML = (r.candidates||[]).map(row=>{
    let legal = row.legal_transitions||[];
    let btns = '';
    if(legal.indexOf('HUMAN_APPROVED')>=0)
      btns += `<button onclick="doResearchAction('RESEARCH_APPROVE','${row.candidate_id}')">Approve</button> `;
    if(legal.indexOf('REJECTED')>=0)
      btns += `<button class="secondary" onclick="doResearchAction('RESEARCH_REJECT','${row.candidate_id}')">Reject</button> `;
    if(!btns) btns = '<span class="note">terminal state -- no transition available</span>';
    let hover = `hypothesis: ${row.hypothesis} | proposed_action: ${row.proposed_action}`
      + ` | exact_gap: ${row.exact_gap} | why: ${row.decision_rationale}`
      + ` | experiment_required: ${row.experiment_required}`
      + ` | unanswered L5 checks: ${(row.unanswered_l5_questions||[]).join(', ') || 'none'}`
      + ` | evidence: ${(row.evidence_refs||[]).join(' ; ')}`;
    return `<tr style="border-bottom:1px solid #edf1f5" title="${String(hover).replace(/"/g,'&quot;')}">`+
      `<td style="padding:4px"><code>${row.candidate_id}</code></td>`+
      `<td style="padding:4px">${row.affected_capability}</td>`+
      `<td style="padding:4px" class="${row.recommendation}">${row.recommendation}</td>`+
      `<td style="padding:4px">${row.overlap_status}</td>`+
      `<td style="padding:4px" class="${row.current_status}">${row.current_status}</td>`+
      `<td style="padding:4px">${row.confidence}</td>`+
      `<td style="padding:4px">${legal.join(', ')||'-'}</td>`+
      `<td style="padding:4px">${btns}</td></tr>`;
  }).join('');
}
async function doResearchAction(command, candidateId){
  // One "note / reason" input feeds both field names: RESEARCH_APPROVE reads
  // `note` (it becomes the ControlPlane approval's note), RESEARCH_REJECT and
  // RESEARCH_HOLD read `reason`. Both are required server-side -- an
  // unexplained governance action is not an audit record.
  let text = val('researchNote');
  let body = {command: command, candidate_id: candidateId, note: text, reason: text,
              reviewer_id: val('researchReviewer'), reviewer_confidence: val('researchConfidence')};
  let r = await postJSON('/api/control', body);
  showIn('researchResult', r.ok, r.data);
  await loadResearch();
}

// Generation Readiness Center card. Same fetch-once + client-side-render shape
// as the AMBA/Research cards above -- computes nothing itself, only renders
// dv_harness.generation_readiness.derive_generation_readiness()'s own real
// twenty-row matrix. The deep-analysis checkbox mirrors the CLI's own
// `--no-deep` flag (skip the SYS-1..SYS-30 cross-subsystem chain; the Flow-B
// topology/command rows then report UNKNOWN with that as the recorded reason,
// never a different verdict for any other row).
// Confidence Calibration card. Same fetch-once + client-side-render shape as
// the Generation Readiness card just below -- computes nothing itself, only
// renders confidence_calibration.calibrate()'s own real per-tier report.
let _confidenceCalibrationData = null;
async function loadConfidenceCalibration(){
  _confidenceCalibrationData = await (await fetch('/api/confidence-calibration')).json();
  renderConfidenceCalibrationTable();
}
function renderConfidenceCalibrationTable(){
  let r = _confidenceCalibrationData;
  let tiles = document.getElementById('confidenceCalibrationTiles');
  let tbody = document.getElementById('confidenceCalibrationTableBody');
  let findings = document.getElementById('confidenceCalibrationFindings');
  if(!r) return;
  if(r.error){
    tiles.innerHTML = tile('ERROR','Confidence Calibration');
    tbody.innerHTML = '<tr><td style="padding:4px" colspan="8" class="err">'+r.error.reason+': '+JSON.stringify(r.error.detail)+'</td></tr>';
    findings.textContent = '';
    return;
  }
  if(!r.available || !r.report){
    tiles.innerHTML = tile('-','Confidence calibration unavailable');
    tbody.innerHTML = '<tr><td style="padding:4px" colspan="8">No calibration report could be produced.</td></tr>';
    findings.textContent = '';
    return;
  }
  let rep = r.report, tiers = rep.tiers || {};
  tiles.innerHTML = [
    tile(rep.status||'-','Status'),
    tile(rep.reason||'-','Reason'),
    tile((rep.calibratable_tiers||[]).length,'Calibratable Tiers'),
    tile((rep.findings||[]).length,'Findings'),
  ].join('');
  tbody.innerHTML = (rep.tier_order||Object.keys(tiers)).map(t=>{
    let row = tiers[t] || {};
    let rel = (row.observed_reliability===null||row.observed_reliability===undefined)
      ? ('-- (' + (row.insufficient_reason||'no history') + ')')
      : (Math.round(row.observed_reliability*1000)/10 + '%');
    return `<tr style="border-bottom:1px solid #edf1f5">`+
      `<td style="padding:4px">${t}</td>`+
      `<td style="padding:4px">${row.records||0}</td>`+
      `<td style="padding:4px">${row.verified||0}</td>`+
      `<td style="padding:4px">${row.rejected||0}</td>`+
      `<td style="padding:4px">${row.determinate||0}</td>`+
      `<td style="padding:4px">${rel}</td>`+
      `<td style="padding:4px">${row.calibratable?'yes':'no'}</td>`+
      `<td style="padding:4px">${(row.declared_floor===null||row.declared_floor===undefined)?'(none)':row.declared_floor}</td></tr>`;
  }).join('') || '<tr><td style="padding:4px" colspan="8">No tier rows produced.</td></tr>';
  findings.innerHTML = (rep.findings && rep.findings.length)
    ? 'Findings: ' + rep.findings.map(f=>`<code>${f.kind}</code>: ${(f.detail||'').toString().replace(/</g,'&lt;')}`).join('; ')
    : 'No findings.';
}

// Cross-Project Pattern Mining (VI-2) -- computes nothing itself, only
// renders cross_project_mining.production_status()/mine_cross_project_patterns()'s
// own real output, exactly like the Confidence Calibration card just above.
let _crossProjectMiningData = null;
async function loadCrossProjectMining(){
  _crossProjectMiningData = await (await fetch('/api/cross-project-mining')).json();
  renderCrossProjectMiningTable();
}
function renderCrossProjectMiningTable(){
  let r = _crossProjectMiningData;
  let tiles = document.getElementById('crossProjectMiningTiles');
  let ptbody = document.getElementById('crossProjectMiningProjectsTableBody');
  let ntbody = document.getElementById('crossProjectMiningPatternsTableBody');
  let disc = document.getElementById('crossProjectMiningDisclosure');
  if(!r) return;
  if(r.error){
    tiles.innerHTML = tile('ERROR','Cross-Project Mining');
    ptbody.innerHTML = '<tr><td style="padding:4px" colspan="5" class="err">'+r.error.reason+': '+JSON.stringify(r.error.detail)+'</td></tr>';
    ntbody.innerHTML = '';
    disc.textContent = '';
    return;
  }
  if(!r.available || !r.status){
    tiles.innerHTML = tile('-','Cross-project mining unavailable');
    ptbody.innerHTML = '<tr><td style="padding:4px" colspan="5">No registry could be read.</td></tr>';
    ntbody.innerHTML = '';
    disc.textContent = '';
    return;
  }
  let st = r.status, mining = r.mining || {};
  tiles.innerHTML = [
    tile(st.registered_project_count||0,'Registered Projects'),
    tile(st.registered_with_readable_store||0,'With Readable Store'),
    tile(mining.status||'-','Mining Status'),
    tile((mining.cross_project_patterns||[]).length,'Cross-Project Patterns'),
    tile(mining.transferable_fix_count||0,'Transferable Fixes'),
    tile(st.can_produce_cross_project_result?'yes':'no','Can Produce Result'),
  ].join('');
  ptbody.innerHTML = (mining.projects||[]).map(p=>
    `<tr style="border-bottom:1px solid #edf1f5">`+
    `<td style="padding:4px">${p.project_id||'-'}</td>`+
    `<td style="padding:4px">${p.root||'-'}</td>`+
    `<td style="padding:4px">${p.readable?'yes':('no ('+(p.skipped_reason||'?')+')')}</td>`+
    `<td style="padding:4px">${p.failure_signature_count||0}</td>`+
    `<td style="padding:4px">${p.verified_fix_count||0}</td></tr>`
  ).join('') || '<tr><td style="padding:4px" colspan="5">No projects registered.</td></tr>';
  ntbody.innerHTML = (mining.cross_project_patterns||[]).map(p=>
    `<tr style="border-bottom:1px solid #edf1f5">`+
    `<td style="padding:4px">${(p.summary||p.signature_key||'-').toString().replace(/</g,'&lt;')}</td>`+
    `<td style="padding:4px">${p.project_count||0}</td>`+
    `<td style="padding:4px">${(p.resolved_in_projects||[]).join(', ')||'-'}</td>`+
    `<td style="padding:4px">${(p.unresolved_in_projects||[]).join(', ')||'-'}</td>`+
    `<td style="padding:4px">${p.transferable_fix?'yes':'no'}</td></tr>`
  ).join('') || '<tr><td style="padding:4px" colspan="5">No cross-project patterns.</td></tr>';
  disc.textContent = mining.disclosure || st.disclosure || '';
}

let _verificationStrategyData = null;
async function loadVerificationStrategy(){
  _verificationStrategyData = await (await fetch('/api/verification-strategy')).json();
  renderVerificationStrategyTable();
}
function renderVerificationStrategyTable(){
  let r = _verificationStrategyData;
  let tiles = document.getElementById('verificationStrategyTiles');
  let tbody = document.getElementById('verificationStrategyTableBody');
  let disclosure = document.getElementById('verificationStrategyDisclosure');
  if(!r) return;
  if(r.error){
    tiles.innerHTML = tile('ERROR','Verification Strategy');
    tbody.innerHTML = '<tr><td style="padding:4px" colspan="5" class="err">'+r.error.reason+': '+JSON.stringify(r.error.detail)+'</td></tr>';
    disclosure.textContent = '';
    return;
  }
  if(!r.available || !r.report){
    tiles.innerHTML = tile('-','Verification strategy unavailable');
    tbody.innerHTML = '<tr><td style="padding:4px" colspan="5">No strategy report could be produced.</td></tr>';
    disclosure.textContent = '';
    return;
  }
  let rep = r.report, recs = rep.recommendations || [];
  tiles.innerHTML = [
    tile((rep.recommended_strategies||[]).length,'Recommended'),
    tile((rep.executable_here||[]).length,'Executable Here'),
    tile((rep.recommend_only||[]).length,'Recommend Only'),
    tile(rep.scope||'-','Scope'),
  ].join('');
  tbody.innerHTML = recs.map(rec=>{
    return `<tr style="border-bottom:1px solid #edf1f5">`+
      `<td style="padding:4px">${rec.strategy||'-'}</td>`+
      `<td style="padding:4px">${rec.verdict||'-'}</td>`+
      `<td style="padding:4px">${rec.executability||'-'}</td>`+
      `<td style="padding:4px">${(rec.basis||[]).join('; ')}</td>`+
      `<td style="padding:4px">${rec.executable_next_action||'-'}</td></tr>`;
  }).join('') || '<tr><td style="padding:4px" colspan="5">No recommendations produced.</td></tr>';
  disclosure.textContent = rep.disclosure || '';
}

let _generationReadinessData = null;
async function loadGenerationReadiness(){
  let deep = document.getElementById('generationReadinessDeep').checked;
  _generationReadinessData = await (await fetch('/api/generation-readiness?deep=' + (deep?'1':'0'))).json();
  renderGenerationReadinessTable();
}
function renderGenerationReadinessTable(){
  let r = _generationReadinessData;
  let tiles = document.getElementById('generationReadinessTiles');
  let tbody = document.getElementById('generationReadinessTableBody');
  let note = document.getElementById('generationReadinessNote');
  if(!r) return;
  if(r.error){
    tiles.innerHTML = tile('ERROR','Generation Readiness');
    tbody.innerHTML = '<tr><td style="padding:4px" colspan="7" class="err">'+r.error.reason+': '+JSON.stringify(r.error.detail)+'</td></tr>';
    note.textContent = '';
    return;
  }
  if(!r.available || !r.matrix){
    tiles.innerHTML = tile('-','Generation readiness unavailable');
    tbody.innerHTML = '<tr><td style="padding:4px" colspan="7">No generation readiness matrix could be produced.</td></tr>';
    note.textContent = '';
    return;
  }
  let m = r.matrix, s = m.summary || {}, byFlow = s.by_flow || {};
  tiles.innerHTML = [
    tile(m.generation_readiness||'-','Overall'),
    tile(s.rows_ready||0,'Ready'), tile(s.rows_partial||0,'Partial'),
    tile(s.rows_blocked||0,'Blocked'), tile(s.rows_unknown||0,'Unknown'),
    tile(byFlow.FLOW_A_SPEC_TO_SUBSYSTEM||'-','Flow A'),
    tile(byFlow.FLOW_B_SUBSYSTEM_TO_SYSTEM||'-','Flow B'),
  ].join('');
  tbody.innerHTML = (m.rows||[]).map(row=>{
    let hover = `capability: ${row.capability} (${row.capability_detail})`
      + ` | project_evidence_status: ${row.project_evidence_status}`
      + ` | flow: ${row.flow} | fact_source: ${(row.fact_source||[]).join(', ')}`
      + ` | basis: ${row.basis}`;
    return `<tr style="border-bottom:1px solid #edf1f5" title="${String(hover).replace(/"/g,'&quot;')}">`+
      `<td style="padding:4px">${row.row}</td>`+
      `<td style="padding:4px" class="${row.status}">${row.status}</td>`+
      `<td style="padding:4px">${row.existing_reuse}</td>`+
      `<td style="padding:4px">${row.evidence}</td>`+
      `<td style="padding:4px">${row.gap}</td>`+
      `<td style="padding:4px">${row.priority}</td>`+
      `<td style="padding:4px">${row.action}</td></tr>`;
  }).join('') || '<tr><td style="padding:4px" colspan="7">No row was produced (section 211\'s twenty rows are mandatory -- this is a bug).</td></tr>';
  note.innerHTML = 'Registered subsystems: ' + (m.registered_subsystems||[]).join(', ') || '(none)'
    + '. Cross-subsystem analysis: <code>' + (m.cross_subsystem_analysis_status||'-') + '</code>'
    + (m.cross_subsystem_analysis_reason ? ' (' + m.cross_subsystem_analysis_reason + ')' : '');
}

let _selfLearningReadinessData = null;
async function loadSelfLearningReadiness(){
  _selfLearningReadinessData = await (await fetch('/api/self-learning-readiness')).json();
  renderSelfLearningReadinessTable();
}
function renderSelfLearningReadinessTable(){
  let r = _selfLearningReadinessData;
  let tiles = document.getElementById('selfLearningReadinessTiles');
  let tbody = document.getElementById('selfLearningReadinessTableBody');
  let note = document.getElementById('selfLearningReadinessNote');
  if(!r) return;
  if(r.error){
    tiles.innerHTML = tile('ERROR','Self-Learning Readiness');
    tbody.innerHTML = '<tr><td style="padding:4px" colspan="5" class="err">'+r.error.reason+': '+JSON.stringify(r.error.detail)+'</td></tr>';
    note.textContent = '';
    return;
  }
  if(!r.available || !r.matrix){
    tiles.innerHTML = tile('-','Self-learning readiness unavailable');
    tbody.innerHTML = '<tr><td style="padding:4px" colspan="5">No self-learning readiness matrix could be produced.</td></tr>';
    note.textContent = '';
    return;
  }
  let m = r.matrix, s = m.summary || {};
  tiles.innerHTML = [
    tile(m.self_learning_readiness||'-','Overall'),
    tile(s.rows_ready||0,'Ready'), tile(s.rows_partial||0,'Partial'),
    tile(s.rows_blocked||0,'Blocked'), tile(s.rows_unknown||0,'Unknown'),
  ].join('');
  tbody.innerHTML = (m.rows||[]).map(row=>{
    let hover = `fact_source: ${(row.fact_source||[]).join(', ')} | basis: ${row.basis}`;
    return `<tr style="border-bottom:1px solid #edf1f5" title="${String(hover).replace(/"/g,'&quot;')}">`+
      `<td style="padding:4px">${row.row}</td>`+
      `<td style="padding:4px" class="${row.status}">${row.status}</td>`+
      `<td style="padding:4px">${row.evidence}</td>`+
      `<td style="padding:4px">${row.gap}</td>`+
      `<td style="padding:4px">${row.next_best_action}</td></tr>`;
  }).join('') || '<tr><td style="padding:4px" colspan="5">No row was produced (section 55\'s 22 rows are mandatory -- this is a bug).</td></tr>';
  note.textContent = m.readiness_rule || '';
}

// Integration Proof Ladder card. Same fetch-once + client-side-render shape
// as the Generation Readiness card just above -- computes nothing itself,
// only renders system_build_proof.py's own real
// SmokeProofReport.to_dict() ladder, read live off
// .dv-harness/system_build_proof/smoke_proof_report.json.
let _smokeProofData = null;
async function loadSmokeProof(){
  _smokeProofData = await (await fetch('/api/system-smoke-proof')).json();
  renderSmokeProofTable();
}
function renderSmokeProofTable(){
  let r = _smokeProofData;
  let tiles = document.getElementById('smokeProofTiles');
  let tbody = document.getElementById('smokeProofTableBody');
  let note = document.getElementById('smokeProofNote');
  if(!r) return;
  if(r.error){
    tiles.innerHTML = tile('ERROR','Integration Proof Ladder');
    tbody.innerHTML = '<tr><td style="padding:4px" colspan="4" class="err">'+r.error.reason+': '+JSON.stringify(r.error.detail)+'</td></tr>';
    note.textContent = 'report path: ' + (r.report_path||'-');
    return;
  }
  if(!r.available || !r.report){
    tiles.innerHTML = tile('-','No smoke-proof report on disk');
    tbody.innerHTML = '<tr><td style="padding:4px" colspan="4">No .dv-harness/system_build_proof/smoke_proof_report.json found. '
      + 'Run <code>dv-harness system-smoke-proof --json &gt; '+(r.report_path||'')+'</code> for a project that has run it.</td></tr>';
    note.textContent = '';
    return;
  }
  let rep = r.report, byStatus = rep.by_status || {};
  tiles.innerHTML = [
    tile(rep.verdict||'-','Verdict'),
    tile(rep.triage_required ? 'YES' : 'no','Triage Required'),
    tile((byStatus.PASS||[]).length,'PASS'),
    tile((byStatus.FAIL||[]).length,'FAIL'),
    tile((byStatus.NOT_AVAILABLE||[]).length,'Not Available'),
    tile((byStatus.PENDING||[]).length,'Pending'),
    tile((byStatus.NOT_YET_RUN||[]).length,'Not Yet Run'),
  ].join('');
  tbody.innerHTML = (rep.rungs||[]).map((rung,i)=>{
    let hover = 'detail: ' + JSON.stringify(rung.detail||{});
    return `<tr style="border-bottom:1px solid #edf1f5" title="${String(hover).replace(/"/g,'&quot;')}">`+
      `<td style="padding:4px">${i+1}</td>`+
      `<td style="padding:4px">${rung.rung}</td>`+
      `<td style="padding:4px" class="${rung.status}">${rung.status}</td>`+
      `<td style="padding:4px">${rung.reason}</td></tr>`;
  }).join('') || '<tr><td style="padding:4px" colspan="4">No rungs in this report.</td></tr>';
  note.innerHTML = 'evidence: ' + (rep.evidence||'-')
    + '. authorizes: <code>' + (rep.authorizes||'-') + '</code>'
    + '. report: <code>' + (r.report_path||'-') + '</code>';
}

// Design Knowledge Explorer card. Same fetch-once + client-side-render shape
// as the Generation Readiness card just above -- computes nothing itself,
// only renders design_knowledge_correlation.correlate()'s own real report
// (sources / facts / provenance / CONFLICT / GAP / DOCUMENTED_VS_IMPLEMENTED
// findings), read live off .dv-harness/design_knowledge/sources.json.
let _designKnowledgeData = null;
function dkConsensusClass(c){
  if(c==='CONFLICT') return 'BLOCKED';
  if(c==='AGREEMENT') return 'PASS';
  return 'UNKNOWN';
}
function dkFindingClass(t){
  if(t==='CONFLICT') return 'BLOCKED';
  return 'PARTIAL'; // GAP / DOCUMENTED_VS_IMPLEMENTED_SPEC_ONLY / _IMPLEMENTATION_ONLY
}
async function loadDesignKnowledge(){
  _designKnowledgeData = await (await fetch('/api/design-knowledge')).json();
  renderDesignKnowledge();
}
function renderDesignKnowledge(){
  let r = _designKnowledgeData;
  let tiles = document.getElementById('designKnowledgeTiles');
  let emptyNote = document.getElementById('designKnowledgeEmptyNote');
  let errNote = document.getElementById('designKnowledgeErrorNote');
  let srcBody = document.getElementById('designKnowledgeSourcesBody');
  let factBody = document.getElementById('designKnowledgeFactsBody');
  let findBody = document.getElementById('designKnowledgeFindingsBody');
  let detail = document.getElementById('designKnowledgeFactDetail');
  if(!r) return;
  detail.innerHTML = '';
  if(r.error){
    tiles.innerHTML = tile('ERROR','Design Knowledge');
    emptyNote.textContent = '';
    errNote.innerHTML = '<span class="err">'+r.error.reason+': '+JSON.stringify(r.error.detail)+'</span>';
    srcBody.innerHTML = ''; factBody.innerHTML = ''; findBody.innerHTML = '';
    return;
  }
  errNote.innerHTML = '';
  if(!r.available || !r.report){
    tiles.innerHTML = tile('-','No sources.json yet');
    emptyNote.innerHTML = 'No <code>sources.json</code> on disk yet at <code>'+(r.sources_path||'')
      + '</code>. Write a real, already-extracted source list there (see '
      + '<code>design_knowledge_correlation.py</code>\'s own module docstring for the shape) to '
      + 'populate this card -- nothing here is fabricated.';
    srcBody.innerHTML = ''; factBody.innerHTML = ''; findBody.innerHTML = '';
    return;
  }
  emptyNote.textContent = '';
  let rep = r.report, s = rep.summary || {}, graph = rep.knowledge_graph || {};
  let nodes = graph.nodes || {}, sources = nodes.sources || [], facts = nodes.facts || [];
  let edges = graph.edges || [];
  tiles.innerHTML = [
    tile(s.source_count||0,'Sources'), tile(s.fact_count||0,'Facts'),
    tile(s.expected_fact_count||0,'Expected Facts'),
    tile(s.conflict_count||0,'Conflicts'), tile(s.gap_count||0,'Gaps'),
    tile(s.documented_vs_implemented_count||0,'Doc vs Impl'),
  ].join('');
  srcBody.innerHTML = sources.map(src=>{
    let n = edges.filter(e=>e.from===src.node_id).length;
    return `<tr style="border-bottom:1px solid #edf1f5">`+
      `<td style="padding:4px">${src.source_id}</td>`+
      `<td style="padding:4px">${src.source_kind}</td>`+
      `<td style="padding:4px">${src.role}</td>`+
      `<td style="padding:4px">${n}</td></tr>`;
  }).join('') || '<tr><td style="padding:4px" colspan="4">No sources.</td></tr>';
  factBody.innerHTML = facts.map((f,i)=>{
    return `<tr style="border-bottom:1px solid #edf1f5;cursor:pointer" onclick="showDesignKnowledgeFact(${i})">`+
      `<td style="padding:4px"><code>${f.fact_key}</code></td>`+
      `<td style="padding:4px">${(f.fact_types||[]).join(', ')}</td>`+
      `<td style="padding:4px" class="${dkConsensusClass(f.consensus)}">${f.consensus}</td>`+
      `<td style="padding:4px">${f.distinct_value_count}</td>`+
      `<td style="padding:4px">${f.assertion_count}</td></tr>`;
  }).join('') || '<tr><td style="padding:4px" colspan="5">No facts.</td></tr>';
  window._designKnowledgeFacts = facts;
  let findings = [
    ...(rep.conflicts||[]), ...(rep.gaps||[]), ...(rep.documented_vs_implemented||[]),
  ];
  findBody.innerHTML = findings.map(fnd=>{
    return `<tr style="border-bottom:1px solid #edf1f5">`+
      `<td style="padding:4px" class="${dkFindingClass(fnd.finding_type)}">${fnd.finding_type}</td>`+
      `<td style="padding:4px"><code>${fnd.fact_key}</code></td>`+
      `<td style="padding:4px">${fnd.reason}</td></tr>`;
  }).join('') || '<tr><td style="padding:4px" colspan="3">No CONFLICT / GAP / DOCUMENTED_VS_IMPLEMENTED findings.</td></tr>';
}
function showDesignKnowledgeFact(i){
  let f = (window._designKnowledgeFacts||[])[i];
  let detail = document.getElementById('designKnowledgeFactDetail');
  if(!f){ detail.innerHTML = ''; return; }
  let rows = (f.provenance||[]).map(p=>
    `<li><code>${p.source_id}</code> (${p.source_kind}, ${p.role}): <b>${JSON.stringify(p.value)}</b>`
    + (p.evidence_ref ? ' -- '+p.evidence_ref : '') + '</li>').join('');
  detail.innerHTML = `Provenance for <code>${f.fact_key}</code>: <ul>${rows}</ul>`;
}

// Requirement/vPlan Center card. Same fetch-once + client-side-render shape
// as the Generation Readiness / Design Knowledge cards above -- computes
// nothing itself, only renders requirement_contract.analyze_requirement_
// contract_set()'s and vplan_artifact.analyze_vplan_completeness()'s own
// real reports, read live off .dv-harness/requirement_vplan/*.json.
let _requirementVplanData = null;
function rvcReqStatusClass(s){
  if(s==='COMPLETE') return 'PASS';
  if(s==='CONTRADICTORY') return 'BLOCKED';
  if(s==='AMBIGUOUS') return 'PARTIAL';
  if(s==='UNKNOWN') return 'UNKNOWN';
  return '';
}
function rvcSeverityClass(s){
  return s==='ERROR' ? 'err' : '';
}
async function loadRequirementVplan(){
  _requirementVplanData = await (await fetch('/api/requirement-vplan-center')).json();
  renderRequirementVplan();
}
function renderRequirementVplan(){
  let r = _requirementVplanData;
  let tiles = document.getElementById('requirementVplanTiles');
  let emptyNote = document.getElementById('requirementVplanEmptyNote');
  let errNote = document.getElementById('requirementVplanErrorNote');
  let reqBody = document.getElementById('requirementBody');
  let reqFindBody = document.getElementById('requirementFindingsBody');
  let dimBody = document.getElementById('vplanDimensionsBody');
  let gapBody = document.getElementById('vplanGapsBody');
  let nextNote = document.getElementById('vplanNextActionsNote');
  if(!r) return;
  if(r.error){
    tiles.innerHTML = tile('ERROR','Requirement/vPlan Center');
    emptyNote.textContent = '';
    errNote.innerHTML = '<span class="err">'+r.error.reason+': '+JSON.stringify(r.error.detail)+'</span>';
    reqBody.innerHTML = ''; reqFindBody.innerHTML = ''; dimBody.innerHTML = ''; gapBody.innerHTML = ''; nextNote.innerHTML = '';
    return;
  }
  errNote.innerHTML = '';
  if(!r.available || (!r.requirement_report && !r.vplan_report)){
    tiles.innerHTML = tile('-','No requirements.json/vplan.json yet');
    emptyNote.innerHTML = 'Neither <code>'+(r.requirements_path||'')+'</code> nor <code>'
      +(r.vplan_path||'')+'</code> exists on disk yet. Write a real, already-extracted requirement/vPlan '
      +'record set there (see <code>requirement_contract.py</code>/<code>vplan_artifact.py</code>\'s own '
      +'module docstrings for the shape) to populate this card -- nothing here is fabricated.';
    reqBody.innerHTML = ''; reqFindBody.innerHTML = ''; dimBody.innerHTML = ''; gapBody.innerHTML = ''; nextNote.innerHTML = '';
    return;
  }
  emptyNote.textContent = '';
  let rr = r.requirement_report, vr = r.vplan_report;
  let counts = (rr && rr.status_counts) || {};
  let dims = (vr && vr.dimensions) || {};
  let dimReadyCount = Object.values(dims).filter(d=>d.status==='READY').length;
  tiles.innerHTML = [
    tile(rr ? (rr.analyzed||0) : '-', 'Requirements Analyzed'),
    tile(rr ? (counts.COMPLETE||0) : '-', 'Complete'),
    tile(rr ? ((counts.PARTIAL||0)+(counts.AMBIGUOUS||0)+(counts.CONTRADICTORY||0)+(counts.UNKNOWN||0)) : '-', 'Not Complete'),
    tile(rr ? (rr.findings||[]).length : '-', 'Requirement Findings'),
    tile(vr ? (vr.row_count||0) : '-', 'vPlan Rows'),
    tile(vr ? (dimReadyCount+'/'+Object.keys(dims).length) : '-', 'Dimensions Ready'),
    tile(vr ? (vr.all_gaps||[]).length : '-', 'vPlan Gaps'),
  ].join('');

  // Requirements table.
  let reqs = (rr && rr.requirements) || [];
  reqBody.innerHTML = reqs.map(row=>{
    let n = (rr.findings||[]).filter(f=>f.requirement_id===row.requirement_id).length;
    return `<tr style="border-bottom:1px solid #edf1f5" title="derived: ${row.derived_status} (${row.derived_reason}) | downstream_consumable: ${row.downstream_consumable} (${row.downstream_consumable_reason})">`+
      `<td style="padding:4px"><code>${row.requirement_id}</code></td>`+
      `<td style="padding:4px" class="${rvcReqStatusClass(row.declared_status)}">${row.declared_status}</td>`+
      `<td style="padding:4px">${n}</td></tr>`;
  }).join('') || '<tr><td style="padding:4px" colspan="3">No requirements.json loaded.</td></tr>';

  // Requirement-level findings table.
  reqFindBody.innerHTML = (rr ? (rr.findings||[]) : []).map(f=>{
    return `<tr style="border-bottom:1px solid #edf1f5">`+
      `<td style="padding:4px" class="${rvcSeverityClass(f.severity)}">${f.severity}</td>`+
      `<td style="padding:4px">${f.code}</td>`+
      `<td style="padding:4px"><code>${f.requirement_id}</code></td>`+
      `<td style="padding:4px">${f.detail}</td></tr>`;
  }).join('') || '<tr><td style="padding:4px" colspan="4">No findings.</td></tr>';

  // vPlan 9-dimension completeness matrix -- never averaged into one score.
  dimBody.innerHTML = Object.values(dims).map(d=>{
    return `<tr style="border-bottom:1px solid #edf1f5">`+
      `<td style="padding:4px">${d.dimension}</td>`+
      `<td style="padding:4px" class="${d.status}">${d.status}</td>`+
      `<td style="padding:4px">${d.satisfied_count}/${d.applicable_count}</td>`+
      `<td style="padding:4px">${(d.gaps||[]).length}</td>`+
      `<td style="padding:4px">${d.reason}</td></tr>`;
  }).join('') || '<tr><td style="padding:4px" colspan="5">No vplan.json loaded.</td></tr>';

  // vPlan gaps (15-value taxonomy) -- gap_severity is carried from the real
  // module-level GAP_SEVERITY table (see _read_requirement_vplan_center_
  // state()'s own comment), never a dashboard-local re-derivation of it.
  let gapSeverity = (vr && vr.gap_severity) || {};
  gapBody.innerHTML = (vr ? (vr.all_gaps||[]) : []).map(g=>{
    let sev = gapSeverity[g.gap] || '-';
    let row = g.row_id || g.requirement_id || '-';
    return `<tr style="border-bottom:1px solid #edf1f5">`+
      `<td style="padding:4px">${g.gap}</td>`+
      `<td style="padding:4px" class="${sev}">${sev}</td>`+
      `<td style="padding:4px"><code>${row}</code></td>`+
      `<td style="padding:4px">${g.detail}</td></tr>`;
  }).join('') || '<tr><td style="padding:4px" colspan="4">No gaps -- every applicable dimension is fully linked.</td></tr>';

  let nba = (vr && vr.next_best_actions) || [];
  nextNote.innerHTML = nba.length
    ? 'Next-Best-Action (inference.next_best_action(), real gap-driven): <ul>'
      + nba.map(a=>'<li><code>'+a.gap+'</code>: '+a.suggested_action+' <i>('+a.source+')</i></li>').join('') + '</ul>'
    : '';
}

// Question Queue card. Same fetch-once + client-side-render shape as the
// Requirement/vPlan card above -- computes nothing itself, only renders
// question_queue.py's own real pending-question/decision/metrics state. The
// two action buttons (Answer / Revoke) go through the EXISTING doControl()
// helper -> POST /api/control, never a question-queue-specific write endpoint.
let _questionQueueData = null;
async function loadQuestionQueue(){
  _questionQueueData = await (await fetch('/api/question-queue')).json();
  renderQuestionQueue();
}
function renderQuestionQueue(){
  let r = _questionQueueData;
  let tiles = document.getElementById('questionQueueTiles');
  let pendBody = document.getElementById('questionQueueTableBody');
  let decBody = document.getElementById('questionQueueDecisionsBody');
  let errNote = document.getElementById('questionQueueErrorNote');
  if(!r) return;
  if(!r.available || r.error){
    tiles.innerHTML = tile('ERROR','Question Queue');
    pendBody.innerHTML = '<tr><td style="padding:4px" colspan="9" class="err">'
      + (r.error ? r.error.reason+': '+JSON.stringify(r.error.detail) : 'unavailable') + '</td></tr>';
    decBody.innerHTML = '';
    errNote.textContent = '';
    return;
  }
  errNote.textContent = '';
  let m = r.metrics || {};
  tiles.innerHTML = [
    tile(r.total_questions||0,'Total Questions'),
    tile((r.pending_questions||[]).length,'Pending'),
    tile((m.self_resolve_rate_percent!==undefined? m.self_resolve_rate_percent.toFixed(1)+'%':'-'),'Self-Resolve Rate'),
    tile((m.blocking_questions_per_week!==undefined? m.blocking_questions_per_week.toFixed(2):'-'),'Blocking/Week'),
    tile((m.repeat_question_rate_percent!==undefined? m.repeat_question_rate_percent.toFixed(1)+'%':'-'),'Repeat Rate'),
    tile((m.assumption_overturned_rate_percent!==undefined? m.assumption_overturned_rate_percent.toFixed(1)+'%':'-'),'Overturned Rate'),
  ].join('');
  let pkgs = r.escalation_packages || {};
  pendBody.innerHTML = (r.pending_questions||[]).map(q=>{
    let options = (q.options||[]).map(o=>o.label).join('; ');
    let pkg = pkgs[q.id] || {};
    let hover = 'category: '+(pkg.category||'-')+' | context: '+(pkg.context||'-')
      + ' | default_if_unanswered: '+(pkg.default_if_unanswered||'-')
      + ' | urgency: '+(pkg.urgency||'-');
    return `<tr style="border-bottom:1px solid #edf1f5" title="${String(hover).replace(/"/g,'&quot;')}">`
      + `<td style="padding:4px"><code>${q.id}</code></td>`
      + `<td style="padding:4px">${q.domain||''}</td>`
      + `<td style="padding:4px">${q.owner||''}</td>`
      + `<td style="padding:4px">${q.status||''}</td>`
      + `<td style="padding:4px">${q.blocking?'yes':'no'}</td>`
      + `<td style="padding:4px">${q.question||''}</td>`
      + `<td style="padding:4px">${options}</td>`
      + `<td style="padding:4px">${q.recommendation||''}</td>`
      + `<td style="padding:4px"><button onclick="doQuestionAnswer('${q.id}')">Answer</button></td></tr>`;
  }).join('') || '<tr><td style="padding:4px" colspan="9" class="note">No pending questions.</td></tr>';
  decBody.innerHTML = (r.decisions||[]).map(q=>{
    return `<tr style="border-bottom:1px solid #edf1f5">`
      + `<td style="padding:4px"><code>${q.id}</code></td>`
      + `<td style="padding:4px"><code>${q.question_key||''}</code></td>`
      + `<td style="padding:4px">${q.status||''}</td>`
      + `<td style="padding:4px">${q.answer||''}</td>`
      + `<td style="padding:4px">${q.decided_by||''}</td>`
      + `<td style="padding:4px">${q.answered_at||''}</td>`
      + `<td style="padding:4px"><button class="secondary" onclick="doQuestionRevoke('${q.question_key||''}')">Revoke</button></td></tr>`;
  }).join('') || '<tr><td style="padding:4px" colspan="7" class="note">No decisions recorded.</td></tr>';
}
async function doQuestionAnswer(questionId){
  let body = {command:'QUESTION_ANSWER', question_id: questionId, answer: val('qqAnswer'),
              basis: val('qqBasis'), decided_by: val('qqDecidedBy')};
  let r = await postJSON('/api/control', body);
  showIn('questionQueueResult', r.ok, r.data);
  await loadQuestionQueue();
}
async function doQuestionRevoke(questionKey){
  let body = {command:'QUESTION_REVOKE', question_key: questionKey, reason: val('qqRevokeReason'),
              revoked_by: val('qqRevokedBy')};
  let r = await postJSON('/api/control', body);
  showIn('questionQueueResult', r.ok, r.data);
  await loadQuestionQueue();
}

// Evidence Integrity + Signoff Blocker Center card. Same fetch-once +
// client-side-render shape as the Requirement/vPlan card above -- computes
// nothing itself, only renders evidence_integrity_states.classify_project_
// evidence_integrity()'s and signoff_blocker_list.derive_signoff_blockers()'s
// own real reports, read live off this project's own real evidence.duckdb /
// signoff freeze store / waiver ledger / functional-coverage evidence.
let _eisData = null;
function eisStateClass(s){
  if(s==='VALID') return 'PASS';
  if(s==='CORRUPT'||s==='CONTRADICTED') return 'BLOCKED';
  if(s==='STALE') return 'PARTIAL';
  if(s==='SUPERSEDED') return 'READY'; // merely-informational, clears -- evidence_integrity_states.py's own docstring
  return 'UNKNOWN'; // UNKNOWN / NOT_AVAILABLE -- "we could not check" is never a pass
}
function eisDimStatusClass(s){
  if(s==='MET') return 'PASS';
  if(s==='UNMET') return 'BLOCKED';
  if(s==='UNKNOWN') return 'UNKNOWN';
  return ''; // NOT_AVAILABLE / NOT_SUPPLIED / AMBIGUOUS_CONFLICTING_SUBMISSIONS -- left unstyled, never guessed
}
function eisSignoffStatusClass(s){
  if(s==='CLOSED') return 'CLOSED';
  if(s==='NOT_CLOSED') return 'BLOCKED';
  return 'UNKNOWN'; // INCOMPLETE_EVIDENCE
}
async function loadEvidenceIntegritySignoffBlockers(){
  _eisData = await (await fetch('/api/evidence-integrity-signoff-blockers')).json();
  renderEvidenceIntegritySignoffBlockers();
}
function renderEvidenceIntegritySignoffBlockers(){
  let r = _eisData;
  let tiles = document.getElementById('eisTiles');
  let errNote = document.getElementById('eisErrorNote');
  let intBody = document.getElementById('eisIntegrityBody');
  let dimBody = document.getElementById('eisDimensionsBody');
  let signoffNote = document.getElementById('eisSignoffNote');
  if(!r) return;
  if(r.error){
    tiles.innerHTML = tile('ERROR','Evidence Integrity / Signoff');
    errNote.innerHTML = '<span class="err">'+r.error.reason+': '+JSON.stringify(r.error.detail)+'</span>';
    intBody.innerHTML = ''; dimBody.innerHTML = ''; signoffNote.innerHTML = '';
    return;
  }
  errNote.innerHTML = '';
  let ir = r.integrity_report, br = r.blocker_report;
  tiles.innerHTML = [
    tile(ir ? (ir.status||'NOT_AVAILABLE') : 'NOT_AVAILABLE', 'Evidence Integrity'),
    tile(ir ? (ir.capsule_count||0) : '-', 'Capsules'),
    tile(ir ? (ir.freeze_count||0) : '-', 'Freezes'),
    tile(br ? (br.signoff_status||'-') : '-', 'Signoff Status'),
    tile(br ? (br.signoff_blockers||[]).length : '-', 'Blockers'),
    tile(br ? (br.incomplete_evidence_dimensions||[]).length : '-', 'Incomplete Evidence'),
  ].join('');

  // Real recorded golden-scenario capsules + signoff freezes -- each carries
  // its own real "state" field (VALID/STALE/SUPERSEDED/CONTRADICTED/
  // CORRUPT/UNKNOWN), never a "status" (that word is this endpoint's OTHER
  // module's own vocabulary -- see the dimensions table below).
  let records = [
    ...((ir && ir.capsules) || []).map(c=>({kind:'capsule', id:c.capsule_id, state:c.state, reasons:(c.reasons||[]).join('; ')})),
    ...((ir && ir.freezes) || []).map(f=>({kind:'freeze', id:f.freeze_id, state:f.state, reasons:(f.reasons||[]).join('; ')})),
  ];
  intBody.innerHTML = records.map(rec=>{
    return `<tr style="border-bottom:1px solid #edf1f5">`+
      `<td style="padding:4px">${rec.kind}</td>`+
      `<td style="padding:4px"><code>${rec.id||'-'}</code></td>`+
      `<td style="padding:4px" class="${eisStateClass(rec.state)}">${rec.state||'-'}</td>`+
      `<td style="padding:4px">${rec.reasons||''}</td></tr>`;
  }).join('') || '<tr><td style="padding:4px" colspan="4">'
    +(ir ? (ir.reason||'No golden-scenario capsules or signoff freezes recorded.') : 'No evidence integrity report available.')
    +'</td></tr>';

  // Real twelve-dimension signoff-blocker rollup, worst-wins -- never
  // averaged. blocker_report.dimensions always carries all twelve, whether
  // or not any of them is currently blocking.
  dimBody.innerHTML = (br ? (br.dimensions||[]) : []).map(d=>{
    return `<tr style="border-bottom:1px solid #edf1f5">`+
      `<td style="padding:4px">${d.dimension_name}</td>`+
      `<td style="padding:4px">${d.in_core_nine ? 'yes' : 'no'}</td>`+
      `<td style="padding:4px" class="${eisDimStatusClass(d.status)}">${d.status}</td>`+
      `<td style="padding:4px">${(d.reasons||[]).join('; ')}</td></tr>`;
  }).join('') || '<tr><td style="padding:4px" colspan="4">No signoff-blocker report available.</td></tr>';

  signoffNote.innerHTML = br
    ? 'signoff_status: <span class="'+eisSignoffStatusClass(br.signoff_status)+'">'+br.signoff_status+'</span>'
      + (br.reason ? ' -- '+br.reason : '')
    : '';
}

// Test Suite Center card. Same fetch-once + client-side-render shape as the
// Requirement/vPlan card just above -- computes nothing itself, only
// renders test_suite_lifecycle.derive_test_suite_lifecycle()'s own real
// per-pattern lifecycle report, read live off .dv-harness/evidence/
// evidence.duckdb.
let _testSuiteCenterData = null;
function tslStateClass(s){
  if(s==='CLOSURE_PROVEN'||s==='VERIFIED_PASS') return 'ok';
  if(s==='VERIFIED_FAIL') return 'err';
  if(s==='UNKNOWN') return 'note';
  return '';
}
async function loadTestSuiteCenter(){
  _testSuiteCenterData = await (await fetch('/api/test-suite-center')).json();
  renderTestSuiteCenter();
}
function renderTestSuiteCenter(){
  let r = _testSuiteCenterData;
  let tiles = document.getElementById('testSuiteCenterTiles');
  let emptyNote = document.getElementById('testSuiteCenterEmptyNote');
  let errNote = document.getElementById('testSuiteCenterErrorNote');
  let body = document.getElementById('testSuitePatternBody');
  if(!r) return;
  if(r.error){
    tiles.innerHTML = tile('ERROR','Test Suite Center');
    emptyNote.textContent = '';
    errNote.innerHTML = '<span class="err">'+r.error.reason+': '+JSON.stringify(r.error.detail)+'</span>';
    body.innerHTML = '';
    return;
  }
  errNote.innerHTML = '';
  if(!r.available || !r.report){
    tiles.innerHTML = tile('-','No evidence.duckdb yet');
    emptyNote.innerHTML = (r.reason || ('No evidence database exists on disk yet for this project. '
      + 'Once a real job/regression is recorded (or a golden_scenario capsule), this card populates '
      + 'live -- nothing here is fabricated.'));
    body.innerHTML = '';
    return;
  }
  emptyNote.textContent = '';
  let rep = r.report;
  let counts = rep.state_counts || {};
  tiles.innerHTML = [
    tile(rep.pattern_count||0, 'Patterns'),
    tile(counts.CLOSURE_PROVEN||0, 'Closure Proven'),
    tile(counts.VERIFIED_PASS||0, 'Verified Pass'),
    tile(counts.VERIFIED_FAIL||0, 'Verified Fail'),
    tile((counts.GENERATED||0)+(counts.SUBMITTED||0)+(counts.JOB_RUNNING||0)+(counts.EXECUTED_UNVERIFIED||0), 'In Progress'),
    tile(counts.UNKNOWN||0, 'Unknown'),
    tile(rep.relationship_count||0, 'Relationships'),
  ].join('');
  body.innerHTML = (rep.patterns||[]).map(p=>{
    let rels = (p.relationships||[]).map(rl=>rl.relation+' ↔ '+(rl.pattern_a===p.pattern?rl.pattern_b:rl.pattern_a)).join('; ');
    return `<tr style="border-bottom:1px solid #edf1f5" title="${p.reason}">`+
      `<td style="padding:4px"><code>${p.pattern}</code></td>`+
      `<td style="padding:4px" class="${tslStateClass(p.lifecycle_state)}">${p.lifecycle_state}</td>`+
      `<td style="padding:4px">${p.job_count}</td>`+
      `<td style="padding:4px">${p.latest_lsf_status||'-'}</td>`+
      `<td style="padding:4px">${p.regression_verdict_passed===true?'PASS':(p.regression_verdict_passed===false?'FAIL':'-')}</td>`+
      `<td style="padding:4px">${(p.golden_capsule_ids||[]).join(', ')||'-'}</td>`+
      `<td style="padding:4px">${rels||'-'}</td></tr>`;
  }).join('') || '<tr><td style="padding:4px" colspan="7">No patterns recorded yet.</td></tr>';
}

// Subsystem Verification Center + System Integration Center card. Same
// fetch-once + client-side-render shape as the Test Suite Center card just
// above -- computes nothing itself, only renders subsystem_contract.py's/
// system_verification_contract.py's/ip_ownership_conflict.py's/
// system_resource_inventory.py's own real reports, read live off this
// project's real registered-subsystem set.
let _ssvData = null;
function ssvCompletenessClass(s){
  if(s==='COMPLETE') return 'PASS';
  if(s==='PARTIAL') return 'PARTIAL';
  if(s==='NOT_AVAILABLE') return 'UNKNOWN';
  return '';
}
function ssvOwnershipClass(s){
  if(s==='CLEAR') return 'PASS';
  if(s==='CONFLICT') return 'BLOCKED';
  return 'UNKNOWN';
}
function ssvCrossCheckClass(s){
  return (s||'').indexOf('UNAVAILABLE')>=0 ? 'UNKNOWN' : 'PASS';
}
async function loadSubsystemSystemVerification(){
  _ssvData = await (await fetch('/api/subsystem-system-verification')).json();
  renderSubsystemSystemVerification();
}
function renderSubsystemSystemVerification(){
  let r = _ssvData;
  let tiles = document.getElementById('ssvTiles');
  let errNote = document.getElementById('ssvErrorNote');
  let subBody = document.getElementById('ssvSubsystemBody');
  let sysNote = document.getElementById('ssvSystemNote');
  let unkBody = document.getElementById('ssvUnknownsBody');
  let errorsNote = document.getElementById('ssvErrorsNote');
  if(!r) return;
  if(r.error){
    tiles.innerHTML = tile('ERROR','Subsystem/System Verification');
    errNote.innerHTML = '<span class="err">'+r.error.reason+': '+JSON.stringify(r.error.detail)+'</span>';
    subBody.innerHTML = ''; sysNote.innerHTML = ''; unkBody.innerHTML = ''; errorsNote.innerHTML = '';
    return;
  }
  errNote.innerHTML = '';
  let subs = r.subsystem_contracts||[];
  let sv = r.system_verification_contract;
  let csf = r.cross_subsystem_findings||{};
  let iocMap = r.ip_ownership_conflicts||{};
  let conflictCount = Object.values(iocMap).filter(x=>x && x.status==='CONFLICT').length;
  tiles.innerHTML = [
    tile(r.system_name||'-','System'),
    tile(sv ? sv.completeness : '-','System Completeness'),
    tile(subs.length,'Subsystems'),
    tile(csf.status||'-','Compatibility'),
    tile((csf.driver_conflicts||[]).length||0,'Driver Conflicts'),
    tile(conflictCount,'IP Ownership Conflicts'),
  ].join('');
  subBody.innerHTML = subs.map(s=>{
    let name = (s.subsystem && (s.subsystem.resolved_name || s.subsystem.requested)) || '(project scope)';
    let key = (s.subsystem && s.subsystem.requested) || '__project__';
    let ioc = iocMap[key] || {};
    let sig = s.signoff || {};
    let stage = (sig.stage && sig.stage.stage_status) || '-';
    return `<tr style="border-bottom:1px solid #edf1f5">`+
      `<td style="padding:4px"><code>${name}</code></td>`+
      `<td style="padding:4px" class="${ssvCompletenessClass(s.completeness)}">${s.completeness}</td>`+
      `<td style="padding:4px">${(s.spec_version||{}).status}/${(s.dut_sha||{}).status}/${(s.tb_sha||{}).status}</td>`+
      `<td style="padding:4px">${(s.protocols||[]).join(', ')||'-'}</td>`+
      `<td style="padding:4px">${(s.regression||{}).status}</td>`+
      `<td style="padding:4px">${stage}</td>`+
      `<td style="padding:4px">${(s.evidence_references||{}).status}</td>`+
      `<td style="padding:4px">${(s.waivers||{}).status}</td>`+
      `<td style="padding:4px" class="${ssvOwnershipClass(ioc.status)}" title="${ioc.reason||''}">${ioc.status||'-'}</td></tr>`;
  }).join('') || '<tr><td style="padding:4px" colspan="9">No registered subsystems, and no project-scope contract could be assembled.</td></tr>';

  if(sv){
    let sc = sv.subsystem_contracts||{};
    let str = sv.system_topology||{};
    let srr = sv.system_resource_registry||{};
    let scr = sv.system_command_registry||{};
    sysNote.innerHTML = 'subsystem_contracts: <span class="'+ssvCompletenessClass(sc.status==='PRESENT'?'':'')+'">'+(sc.status||'-')+'</span>'
      +' (count='+(sc.count||0)+') &nbsp;|&nbsp; system_topology: <span class="'+ssvCrossCheckClass(str.status)+'">'+(str.status||'-')+'</span>'
      +' &nbsp;|&nbsp; system_resource_registry: <span class="'+ssvCrossCheckClass(srr.status)+'">'+(srr.status||'-')+'</span>'
      + (srr.preferred_model ? (' (preferred_model: '+srr.preferred_model+')') : '')
      +' &nbsp;|&nbsp; system_command_registry: <span class="'+ssvCrossCheckClass(scr.status)+'">'+(scr.status||'-')+'</span>'
      + (scr.blocking_collisions ? (' (blocking_collisions='+scr.blocking_collisions+')') : '');
    unkBody.innerHTML = (sv.unknowns||[]).map(u=>{
      return `<tr style="border-bottom:1px solid #edf1f5"><td style="padding:4px">${u.field}</td><td style="padding:4px">${u.reason}</td></tr>`;
    }).join('') || '<tr><td style="padding:4px" colspan="2">No unknowns -- every tracked aspect was assembled from a real source.</td></tr>';
  } else {
    sysNote.innerHTML = '';
    unkBody.innerHTML = '';
  }

  let errs = r.errors||[];
  errorsNote.innerHTML = errs.length
    ? '<span class="err">'+errs.map(e=>(e.subsystem||'(project)')+'/'+e.stage+': '+e.message).join('; ')+'</span>'
    : '';
}

// Verification Architecture View card. Same fetch-once + client-side-render
// shape as the Requirement/vPlan card just above -- computes nothing itself,
// only renders verification_architecture.assemble_verification_architecture()'s
// own real 5 matrices (already rendered to markdown by that module's own
// render_*_matrix() functions -- shown verbatim in a <pre>, never
// re-tabulated here) plus its two real comparators, read live off
// .dv-harness/verification_architecture/inputs.json.
let _verificationArchitectureData = null;
function vaSeverityClass(s){
  if(s==='HIGH') return 'err';
  if(s==='MEDIUM') return 'PARTIAL';
  return '';
}
async function loadVerificationArchitecture(){
  _verificationArchitectureData = await (await fetch('/api/verification-architecture')).json();
  renderVerificationArchitecture();
}
function renderVerificationArchitecture(){
  let r = _verificationArchitectureData;
  let tiles = document.getElementById('verificationArchitectureTiles');
  let emptyNote = document.getElementById('verificationArchitectureEmptyNote');
  let errNote = document.getElementById('verificationArchitectureErrorNote');
  let vipBindPre = document.getElementById('vaVipBindMatrix');
  let ifacePre = document.getElementById('vaInterfaceMatrix');
  let checkerPre = document.getElementById('vaCheckerMatrix');
  let assertionPre = document.getElementById('vaAssertionMatrix');
  let scoreboardPre = document.getElementById('vaScoreboardMatrix');
  let conflictsBody = document.getElementById('vaConflictsBody');
  let duplicatesBody = document.getElementById('vaDuplicatesBody');
  if(!r) return;
  let clearAll = ()=>{
    vipBindPre.textContent=''; ifacePre.textContent=''; checkerPre.textContent='';
    assertionPre.textContent=''; scoreboardPre.textContent='';
    conflictsBody.innerHTML=''; duplicatesBody.innerHTML='';
  };
  if(r.error){
    tiles.innerHTML = tile('ERROR','Verification Architecture');
    emptyNote.textContent = '';
    errNote.innerHTML = '<span class="err">'+r.error.reason+': '+JSON.stringify(r.error.detail)+'</span>';
    clearAll();
    return;
  }
  errNote.innerHTML = '';
  if(!r.available || !r.document){
    tiles.innerHTML = tile('-','No inputs.json yet');
    emptyNote.innerHTML = 'No <code>'+(r.inputs_path||'')+'</code> exists on disk yet. Write a real, '
      +'already-assembled set of keyword arguments there (see '
      +'<code>verification_architecture.assemble_verification_architecture()</code>\'s own docstring '
      +'for the shape) to populate this card -- nothing here is fabricated.';
    clearAll();
    return;
  }
  emptyNote.textContent = '';
  let doc = r.document;
  let matrices = doc.matrices || {};
  let conflicts = doc.placement_conflicts || [];
  let duplicates = doc.intra_subsystem_duplicates || [];
  tiles.innerHTML = [
    tile((doc.vip_bind||[]).length,'VIP Binds'),
    tile((doc.checker||[]).length,'Checkers'),
    tile((doc.scoreboard||[]).length,'Scoreboards'),
    tile((doc.assertion||[]).length,'Assertions'),
    tile(conflicts.length,'Placement Conflicts'),
    tile(duplicates.length,'Intra-Subsystem Duplicates'),
  ].join('');
  vipBindPre.textContent = matrices.vip_bind || '';
  ifacePre.textContent = matrices.interface_to_verification || '';
  checkerPre.textContent = matrices.function_to_checker || '';
  assertionPre.textContent = matrices.assertion_placement || '';
  scoreboardPre.textContent = matrices.scoreboard_architecture || '';
  conflictsBody.innerHTML = conflicts.map(f=>{
    return `<tr style="border-bottom:1px solid #edf1f5">`+
      `<td style="padding:4px">${f.kind}</td>`+
      `<td style="padding:4px" class="${vaSeverityClass(f.severity)}">${f.severity}</td>`+
      `<td style="padding:4px">${f.summary}</td></tr>`;
  }).join('') || '<tr><td style="padding:4px" colspan="3">No placement conflicts.</td></tr>';
  duplicatesBody.innerHTML = duplicates.map(f=>{
    return `<tr style="border-bottom:1px solid #edf1f5">`+
      `<td style="padding:4px">${f.kind}</td>`+
      `<td style="padding:4px" class="${vaSeverityClass(f.severity)}">${f.severity}</td>`+
      `<td style="padding:4px">${f.summary}</td></tr>`;
  }).join('') || '<tr><td style="padding:4px" colspan="3">No intra-subsystem duplicates.</td></tr>';
}

// System Transaction View + End-to-End Scoreboard card. Same fetch-once +
// client-side-render shape as the Verification Architecture card above --
// computes nothing itself, only renders three real modules' own reports
// (system_transaction_ir.py / transaction_correlation_ir.py /
// system_scoreboard_ir.py), read live off
// .dv-harness/system_transaction_e2e_scoreboard/inputs.json. Each section's
// own markdown render is shown verbatim inside its own <pre>, matching this
// page's own established backend-rendered-text convention (see the
// Verification Architecture card's five matrix <pre> blocks).
let _steData = null;
async function loadSystemTransactionE2EScoreboard(){
  _steData = await (await fetch('/api/system-transaction-e2e-scoreboard')).json();
  renderSystemTransactionE2EScoreboard();
}
function renderSystemTransactionE2EScoreboard(){
  let r = _steData;
  let tiles = document.getElementById('steTiles');
  let emptyNote = document.getElementById('steEmptyNote');
  let errNote = document.getElementById('steErrorNote');
  let stPre = document.getElementById('steSystemTransactionPre');
  let tcPre = document.getElementById('steTransactionCorrelationPre');
  let ssPre = document.getElementById('steSystemScoreboardPre');
  if(!r) return;
  let clearAll = ()=>{ stPre.textContent=''; tcPre.textContent=''; ssPre.textContent=''; };
  if(r.error){
    tiles.innerHTML = tile('ERROR','System Transaction / E2E Scoreboard');
    emptyNote.textContent = '';
    errNote.innerHTML = '<span class="err">'+r.error.reason+': '+JSON.stringify(r.error.detail)+'</span>';
    clearAll();
    return;
  }
  errNote.innerHTML = '';
  if(!r.available){
    tiles.innerHTML = tile('-','No inputs.json yet');
    emptyNote.innerHTML = 'No <code>'+(r.inputs_path||'')+'</code> exists on disk yet. Write a real, '
      +'already-declared <code>{system_transaction, transaction_correlation, system_scoreboard}</code> '
      +'overlay there (see each module\\'s own docstring for its shape) to populate this card -- '
      +'nothing here is fabricated.';
    clearAll();
    return;
  }
  emptyNote.textContent = '';
  let st = r.system_transaction || {}, tc = r.transaction_correlation || {}, ss = r.system_scoreboard || {};
  let stRep = st.report || {}, ssRep = ss.report || {};
  let logicalCount = (tc.logical_transactions||[]).length;
  let logicalComplete = (tc.logical_transactions||[]).filter(e=>e.status==='LOGICAL_TXN_COMPLETE').length;
  tiles.innerHTML = [
    tile(stRep.overall_status||'-','System Transaction Composition'),
    tile((stRep.entries||[]).length,'Transaction Links'),
    tile(logicalCount,'Logical Transactions'),
    tile(logicalComplete,'Complete'),
    tile(ssRep.overall_status||'-','Scoreboard Composition'),
    tile((ssRep.entries||[]).length,'System Interactions'),
  ].join('');
  stPre.textContent = st.error ? (st.error.reason+': '+JSON.stringify(st.error.detail)) : (st.markdown || '');
  tcPre.textContent = tc.error ? (tc.error.reason+': '+JSON.stringify(tc.error.detail))
    : (tc.markdown || '(no transaction correlation facts declared)');
  ssPre.textContent = ss.error ? (ss.error.reason+': '+JSON.stringify(ss.error.detail)) : (ss.markdown || '');
}

// VIP/UVM Environment Builder card. Same fetch-once + client-side-render
// shape as the Verification Architecture card just above -- computes
// nothing itself, only renders protocol_capability.py's real per-protocol
// capability_status (reused, the same real data the Protocols tiles above
// already show) plus vip_api_card.validate_vip_api_usage()'s real PROVEN/
// BLOCKED/UNPROVABLE citation report, read live off
// .dv-harness/vip_evidence/inputs.json.
let _vipEnvBuilderData = null;
async function loadVipEnvironmentBuilder(){
  _vipEnvBuilderData = await (await fetch('/api/vip-environment-builder')).json();
  renderVipEnvironmentBuilder();
}
function renderVipEnvironmentBuilder(){
  let r = _vipEnvBuilderData;
  let protocolTiles = document.getElementById('vipEnvBuilderProtocolTiles');
  let tiles = document.getElementById('vipEnvBuilderTiles');
  let emptyNote = document.getElementById('vipEnvBuilderEmptyNote');
  let errNote = document.getElementById('vipEnvBuilderErrorNote');
  let blockedBody = document.getElementById('vipEnvBuilderBlockedBody');
  let unprovableBody = document.getElementById('vipEnvBuilderUnprovableBody');
  let provenBody = document.getElementById('vipEnvBuilderProvenBody');
  if(!r) return;
  // Protocol capability tiles render unconditionally -- real registry data
  // needing no vip_evidence inputs.json at all (same _protocol_registry()
  // source the Protocols card above already reads).
  let protocols = r.protocols||[];
  protocolTiles.innerHTML = protocols.length
    ? protocols.map(p=>`<div class="tile" title="protocol model generator: ${p.protocol_model_generator||'NONE'}">`+
        `<div class="n">${p.capability_status||'-'}</div><div class="l">${p.name}</div></div>`).join('')
    : tile('-','No protocols registered');
  let clearAll = ()=>{ blockedBody.innerHTML=''; unprovableBody.innerHTML=''; provenBody.innerHTML=''; tiles.innerHTML=''; };
  if(r.error){
    errNote.innerHTML = '<span class="err">'+r.error.reason+': '+JSON.stringify(r.error.detail)+'</span>';
    emptyNote.textContent = '';
    clearAll();
    return;
  }
  errNote.innerHTML = '';
  if(!r.available || !r.report){
    emptyNote.innerHTML = 'No <code>'+(r.inputs_path||'')+'</code> exists on disk yet. Write a real '
      +'{"sources": [...], "index_path": "..."} document there (see '
      +'<code>vip_api_card.validate_vip_api_usage()</code>\'s own docstring for the shape) to '
      +'populate this card -- nothing here is fabricated.';
    clearAll();
    return;
  }
  emptyNote.textContent = '';
  let rep = r.report;
  let counts = rep.counts||{};
  tiles.innerHTML = [
    tile(rep.status||'-','Overall Status'),
    tile(counts.PROVEN||0,'PROVEN'),
    tile(counts.BLOCKED||0,'BLOCKED'),
    tile(counts.UNPROVABLE||0,'UNPROVABLE'),
    tile(counts.OUT_OF_SCOPE||0,'OUT_OF_SCOPE'),
    tile(rep.files_scanned!=null?rep.files_scanned:'-','Files Scanned'),
  ].join('');
  let cards = rep.cards||[];
  let byStatus = s => cards.filter(c=>c.status===s);
  blockedBody.innerHTML = byStatus('BLOCKED').map(c=>
    `<tr style="border-bottom:1px solid #edf1f5">`+
    `<td style="padding:4px">${c.citation}</td>`+
    `<td style="padding:4px" class="err">${c.reason||''}</td>`+
    `<td style="padding:4px">${c.usage_file}:${c.usage_line}</td></tr>`
  ).join('') || '<tr><td style="padding:4px" colspan="3">No BLOCKED citations.</td></tr>';
  unprovableBody.innerHTML = byStatus('UNPROVABLE').map(c=>
    `<tr style="border-bottom:1px solid #edf1f5">`+
    `<td style="padding:4px">${c.citation}</td>`+
    `<td style="padding:4px" class="PARTIAL">${c.reason||''}</td>`+
    `<td style="padding:4px">${c.usage_file}:${c.usage_line}</td></tr>`
  ).join('') || '<tr><td style="padding:4px" colspan="3">No UNPROVABLE citations.</td></tr>';
  provenBody.innerHTML = byStatus('PROVEN').map(c=>{
    let loc = (c.resolved_file && c.resolved_line!=null) ? (c.resolved_file+':'+c.resolved_line) : '(no location)';
    let via = (c.declared_by && c.declared_by!==c.vip_class) ? (c.declared_by+' (via inheritance)') : (c.declared_by||'');
    return `<tr style="border-bottom:1px solid #edf1f5">`+
      `<td style="padding:4px">${c.citation}</td>`+
      `<td style="padding:4px">${loc}</td>`+
      `<td style="padding:4px">${via}</td></tr>`;
  }).join('') || '<tr><td style="padding:4px" colspan="3">No PROVEN citations.</td></tr>';
}

// Orphaned/Leaked-Fork Detection card. Same fetch-once + client-side-render
// shape as the VIP/Environment Builder card just above -- computes nothing
// itself, only renders orphaned_fork_detection.py's real branch_b*-dispatch/
// wait pairing report, read live off
// .dv-harness/orphaned_fork_detection/inputs.json.
let _orphanedForkData = null;
async function loadOrphanedForkDetection(){
  _orphanedForkData = await (await fetch('/api/orphaned-fork-detection')).json();
  renderOrphanedForkDetection();
}
function orphanedForkFileClass(s){
  if(s==='FINDINGS_FOUND') return 'BLOCKED';
  if(s==='UNREADABLE') return 'UNKNOWN';
  if(s==='NOT_APPLICABLE') return 'NOT_STARTED';
  return 'PASS'; // CLEAN
}
async function loadMultiVipCooperation(){
  _multiVipCoopData = await (await fetch('/api/multi-vip-cooperation')).json();
  renderMultiVipCooperation();
}
let _multiVipCoopData = null;
function renderOrphanedForkDetection(){
  let r = _orphanedForkData;
  let tiles = document.getElementById('orphanedForkTiles');
  let emptyNote = document.getElementById('orphanedForkEmptyNote');
  let errNote = document.getElementById('orphanedForkErrorNote');
  let body = document.getElementById('orphanedForkFilesBody');
  if(!r) return;
  if(r.error){
    errNote.innerHTML = '<span class="err">'+r.error.reason+': '+JSON.stringify(r.error.detail)+'</span>';
    emptyNote.textContent = ''; tiles.innerHTML = ''; body.innerHTML = '';
    return;
  }
  errNote.innerHTML = '';
  if(!r.available || !r.report){
    emptyNote.innerHTML = 'No <code>'+(r.inputs_path||'')+'</code> exists on disk yet. Write a real '
      +'{"pattern_dir": "...", "glob"?: "*.txt"} document there (see '
      +'<code>orphaned_fork_detection.analyze_pattern_directory()</code>\'s own docstring for the '
      +'shape) to populate this card -- nothing here is fabricated.';
    tiles.innerHTML = ''; body.innerHTML = '';
    return;
  }
  emptyNote.textContent = '';
  let rep = r.report;
  tiles.innerHTML = [
    tile(rep.overall_status||'-','Overall Status'),
    tile((rep.files_scanned||[]).length,'Files Scanned'),
    tile(rep.orphaned_dispatch_count||0,'Orphaned Dispatches'),
    tile(rep.unclosed_region_count||0,'Unclosed Regions'),
  ].join('');
  body.innerHTML = (rep.reports||[]).map(fr=>
    `<tr style="border-bottom:1px solid #edf1f5">`+
    `<td style="padding:4px">${fr.file}</td>`+
    `<td style="padding:4px" class="${orphanedForkFileClass(fr.status)}">${fr.status}</td>`+
    `<td style="padding:4px">${fr.reason||''}</td>`+
    `<td style="padding:4px">${(fr.regions||[]).length}</td></tr>`
  ).join('') || '<tr><td style="padding:4px" colspan="4">No files scanned.</td></tr>';
}

// Multi-VIP Cooperation Architecting card. Same fetch-once + client-side-
// render shape as the Orphaned/Leaked-Fork Detection card just above --
// computes nothing itself, only renders multi_vip_cooperation_architecting.
// py's real build_multi_vip_cooperation() report, read live off
// .dv-harness/multi_vip_cooperation/inputs.json.
function multiVipCoopStatusClass(s){
  if(s==='COOPERATION_ARCHITECTED') return 'PASS';
  if(s==='COOPERATION_DETECTED_ARCHITECTURE_INCOMPLETE') return 'BLOCKED';
  if(s==='INSUFFICIENT_EVIDENCE') return 'UNKNOWN';
  return 'NOT_STARTED'; // NO_MULTI_VIP_COOPERATION_DETECTED
}
function renderMultiVipCooperation(){
  let r = _multiVipCoopData;
  let tiles = document.getElementById('multiVipCoopTiles');
  let emptyNote = document.getElementById('multiVipCoopEmptyNote');
  let errNote = document.getElementById('multiVipCoopErrorNote');
  let body = document.getElementById('multiVipCoopRelBody');
  if(!r) return;
  if(r.error){
    errNote.innerHTML = '<span class="err">'+r.error.reason+': '+JSON.stringify(r.error.detail)+'</span>';
    emptyNote.textContent = ''; tiles.innerHTML = ''; body.innerHTML = '';
    return;
  }
  errNote.innerHTML = '';
  if(!r.available || !r.report){
    emptyNote.innerHTML = 'No <code>'+(r.inputs_path||'')+'</code> exists on disk yet. Write a real '
      +'{"interfaces": [...], "env_manifest"?, "rtl_modules"?, "declared_coupling_facts"?, '
      +'"sequencing_relations"?, "sequencing_observations"?} document there (see '
      +'<code>multi_vip_cooperation_architecting.build_multi_vip_cooperation()</code>\'s own '
      +'docstring for the shape) to populate this card -- nothing here is fabricated.';
    tiles.innerHTML = ''; body.innerHTML = '';
    return;
  }
  emptyNote.textContent = '';
  let rep = r.report;
  let rels = rep.relationships||[];
  tiles.innerHTML = [
    tile(rep.overall_status||'-','Overall Status'),
    tile((rep.interfaces||[]).length,'Interfaces'),
    tile(rels.length,'Coupled Pairs'),
  ].join('');
  body.innerHTML = rels.map(x=>
    `<tr style="border-bottom:1px solid #edf1f5">`+
    `<td style="padding:4px">${x.interface_a}</td>`+
    `<td style="padding:4px">${x.interface_b}</td>`+
    `<td style="padding:4px" class="${multiVipCoopStatusClass(x.cooperation_status)}">${x.cooperation_status||''}</td>`+
    `<td style="padding:4px">${x.architecture_status||''}</td>`+
    `<td style="padding:4px">${(x.sequencing_dependency||{}).status||''}</td>`+
    `<td style="padding:4px">${(x.virtual_sequencer_composition||{}).composition_mode||''}</td></tr>`
  ).join('') || '<tr><td style="padding:4px" colspan="6">No coupled interface pairs -- no multi-VIP cooperation detected.</td></tr>';
}

// DUT Errata/Known-Issues Correlation card. Same fetch-once + client-side-
// render shape as the Multi-VIP Cooperation card just above -- computes
// nothing itself, only renders dut_errata_correlation.py's real
// analyze_errata() report, read live off
// .dv-harness/dut_errata_correlation/inputs.json (source_path) plus this
// project's own real env.manifest.json (manifest_path, auto-resolved --
// never declared by the caller).
let _dutErrataData = null;
async function loadDutErrataCorrelation(){
  _dutErrataData = await (await fetch('/api/dut-errata-correlation')).json();
  renderDutErrataCorrelation();
}
function dutErrataStatusClass(s){
  if(s==='RTL_LOCATED') return 'PASS';
  if(s==='RTL_PARTIALLY_LOCATED') return 'PARTIAL';
  if(s==='RTL_NOT_LOCATED') return 'BLOCKED';
  if(s==='NO_AFFECTED_COMPONENT_CITED') return 'NOT_STARTED';
  return 'UNKNOWN'; // NOT_AVAILABLE
}
function renderDutErrataCorrelation(){
  let r = _dutErrataData;
  let tiles = document.getElementById('dutErrataTiles');
  let errNote = document.getElementById('dutErrataErrorNote');
  let body = document.getElementById('dutErrataBody');
  if(!r) return;
  if(r.error){
    errNote.innerHTML = '<span class="err">'+r.error.reason+': '+JSON.stringify(r.error.detail)+'</span>';
  } else { errNote.innerHTML = ''; }
  let rep = r.report;
  if(!rep){ tiles.innerHTML = tile('-','No report'); body.innerHTML = ''; return; }
  let sum = rep.summary||{};
  tiles.innerHTML = [
    tile(rep.status||'-','Status'),
    tile(rep.erratum_count||0,'Errata'),
    tile(sum.RTL_LOCATED||0,'RTL_LOCATED'),
    tile(sum.RTL_NOT_LOCATED||0,'RTL_NOT_LOCATED'),
  ].join('');
  if(rep.status!=='ANALYZED'){
    body.innerHTML = '<tr><td style="padding:4px" colspan="4">'+(rep.reason||'No errata/known-issues '
      +'document declared -- write {"source_path": "...", "title"?} to <code>'+(r.inputs_path||'')
      +'</code> to populate this card.')+'</td></tr>';
    return;
  }
  body.innerHTML = (rep.errata||[]).map(e=>
    `<tr style="border-bottom:1px solid #edf1f5">`+
    `<td style="padding:4px">${e.erratum_id||''}</td>`+
    `<td style="padding:4px">${e.title||''}</td>`+
    `<td style="padding:4px" class="${dutErrataStatusClass(e.correlation_status)}">${e.correlation_status||''}</td>`+
    `<td style="padding:4px">${(e.citations||[]).map(c=>c.name).join(', ')}</td></tr>`
  ).join('') || '<tr><td style="padding:4px" colspan="4">No errata extracted.</td></tr>';
}

// Loop Engineering Center card (LOOP-4, section 107). Joined to load()'s 3s
// poll, unlike the Memory card below and like the AMBA/Research cards: a
// running loop changes state on every iteration, and "why is this loop still
// running" is the one question this card exists to answer -- an answer three
// seconds stale is the whole point of a live control plane. Reading it is a
// plain tail of events.jsonl plus one catalog lookup: no gate runs, no
// subprocess, no database is opened by the read itself.
let _loopData = null;
async function loadLoopCenter(){
  _loopData = await (await fetch('/api/loops')).json();
  renderLoopCenter();
}
function renderLoopCenter(){
  let r = _loopData;
  if(!r) return;
  let head = document.getElementById('loopCenterTableHead');
  let tbody = document.getElementById('loopCenterTableBody');
  let note = document.getElementById('loopCenterNote');
  let scan = document.getElementById('loopCenterScan');
  // The eight column labels come from section 107 over the wire
  // (loop_telemetry.SECTION_107_COLUMNS), never a hardcoded copy in this page.
  head.innerHTML = '<tr style="text-align:left;border-bottom:1px solid #d9e1ec">'
    + (r.columns||[]).map(c=>'<th style="padding:4px">'+c.label+'</th>').join('') + '</tr>';
  let s = r.scan||{};
  scan.textContent = s.lines_scanned==null ? '' :
    (s.loop_events+' loop event(s) in the last '+s.lines_scanned+' audit line(s)'
     + (s.scan_truncated ? ' -- scan capped at '+s.scan_limit+', older sessions not shown' : ''));
  if(!r.available){
    note.innerHTML = 'No loop telemetry yet. <code>'+(r.reason||'')+'</code>';
    tbody.innerHTML = '<tr><td style="padding:4px" colspan="'+((r.columns||[]).length||8)
      + '">Nothing to show yet.</td></tr>';
    document.getElementById('loopCenterDetail').style.display = 'none';
    return;
  }
  note.innerHTML = 'Click a row for the section-107 drill-down (Goal, Trigger, Iteration '
    + 'History, Evidence, Verifier, Progress Delta, Budget Remaining, Retry/Backoff, '
    + 'Next-Best-Action, Human Gate, Stop Reason, Resume Condition).';
  tbody.innerHTML = (r.rows||[]).map(row=>{
    let vg = row.verified_gain||null;
    let gain = !vg ? '-' : (vg.value+'/'+vg.total+' '+vg.metric
      + (vg.delta===null||vg.delta===undefined ? '' : ' ('+(vg.delta>=0?'+':'')+vg.delta+')'));
    let b = row.budget||null;
    let budget = !b ? '-' : (b.attempts+'/'+b.max_stage_retries+' attempts'
      + (b.event==='LOOP_BUDGET_EXHAUSTED' ? ' <span class="err">EXHAUSTED</span>'
         : (b.event==='LOOP_BUDGET_WARNING' ? ' <span class="warn">last retry</span>' : '')));
    let stateCls = (row.state==='SUCCESS'||row.state==='CONVERGING') ? 'ok'
      : ((row.state==='FAILED'||row.state==='BLOCKED'||row.state==='BUDGET_EXHAUSTED'
          ||row.state==='PLATEAU'||row.state==='OSCILLATING') ? 'err' : '');
    return '<tr style="border-bottom:1px solid #edf1f5;cursor:pointer" '
      + 'onclick="showLoopDetail(\''+row.run_id+'\')" title="run_id: '+row.run_id+'">'
      + '<td style="padding:4px">'+row.loop+'</td>'
      + '<td style="padding:4px"><span class="'+stateCls+'">'+row.state+'</span></td>'
      + '<td style="padding:4px">'+row.iteration+'</td>'
      + '<td style="padding:4px">'+gain+'</td>'
      + '<td style="padding:4px">'+budget+'</td>'
      + '<td style="padding:4px">'+row.plateau+'</td>'
      + '<td style="padding:4px">'+row.oscillation+'</td>'
      + '<td style="padding:4px">'+(row.next_action||'-')+'</td></tr>';
  }).join('') || ('<tr><td style="padding:4px" colspan="'+(r.columns||[]).length
      + '">No loop session in the scanned window.</td></tr>');
}
function showLoopDetail(runId){
  let el = document.getElementById('loopCenterDetail');
  let d = ((_loopData||{}).sessions||{})[runId];
  el.style.display = 'block';
  if(!d){ el.textContent = 'No drill-down recorded for '+runId; return; }
  // Rendered in section 107's own field ORDER, straight off the wire -- this
  // page invents no field and reorders none.
  let fields = (_loopData.drilldown_fields||[]);
  el.textContent = fields.map(f=>{
    let v = d[f.key];
    if(v===null||v===undefined||v==='') return f.label+': -';
    return f.label+': ' + (typeof v==='string' ? v : JSON.stringify(v, null, 1));
  }).join('\\n\\n');
}

// Agent Activity card (GUI-06). Fetch-once + render, same shape as the Loop
// Engineering Center just above -- renders only the real AgentTaskStore
// tasks.json/ownership.json rows _read_agent_activity_state() already joined
// on task_id, never a dashboard-local re-derivation of ownership or a guessed
// stage correlation (see that function's own comment for why no react-record
// join is attempted).
async function loadAgentActivity(){
  let r = await (await fetch('/api/agent-activity')).json();
  let tiles = document.getElementById('agentActivityTiles');
  let tbody = document.getElementById('agentActivityTableBody');
  if(!r.available){
    tiles.innerHTML = tile('-','No agent task ever delegated');
    tbody.innerHTML = '<tr><td style="padding:4px" colspan="8">No AgentTaskStore ledger yet (looked for '+r.tasks_path+'). A task appears here the first time this project runs a stage.</td></tr>';
    return;
  }
  let s = r.summary||{}, sc = s.status_counts||{};
  tiles.innerHTML = [
    tile(s.task_count||0,'Delegated Tasks'), tile(sc.RUNNING||0,'Running'),
    tile(sc.NOT_STARTED||0,'Not Started'), tile(sc.COMPLETED||0,'Completed'),
    tile(sc.FAILED||0,'Failed'), tile(s.claimed_resource_count||0,'Claimed Resources')
  ].join('');
  tbody.innerHTML = (r.rows||[]).map(row=>{
    let last = row.completed_at ? ('done '+fmtTs(row.completed_at))
      : (row.started_at ? ('started '+fmtTs(row.started_at)) : 'not started');
    if(row.duration_sec!=null) last += ' ('+row.duration_sec.toFixed(1)+'s)';
    return '<tr style="border-bottom:1px solid #edf1f5" title="task_id: '+row.task_id+'">'
      + '<td style="padding:4px"><code>'+(row.task_id||'-')+'</code></td>'
      + '<td style="padding:4px">'+(row.agent||'-')+'</td>'
      + '<td style="padding:4px">'+(row.route||'-')+'</td>'
      + '<td style="padding:4px">'+((row.skills||[]).join(', ')||'-')+'</td>'
      + '<td style="padding:4px">'+(row.parallel_group||'-')+'</td>'
      + '<td style="padding:4px">'+((row.owned_resources||[]).join(', ')||'-')+'</td>'
      + '<td style="padding:4px" class="'+row.status+'">'+row.status+'</td>'
      + '<td style="padding:4px">'+last+'</td></tr>';
  }).join('') || '<tr><td style="padding:4px" colspan="8">Ledger present but no task recorded.</td></tr>';
}

// Memory + Obsidian Knowledge Center card (GUI-11). Fetched once on page load
// and again on an explicit Search -- deliberately NOT joined to load()'s 3s
// poll, unlike the AMBA/Research cards above: durable knowledge tiers change
// on a promotion, not per second, and memory_vault.get_active_provider()
// runs a real capability probe (detect_obsidian_cli(): PATH lookups plus a
// `--version` subprocess when a binary is found) that has no business firing
// every three seconds on an HTTP thread. Same fetch-once convention the
// Sessions and User Info cards already use.
let _memoryData = null;
async function loadMemoryCenter(){
  let qs = '?q=' + encodeURIComponent(val('memoryNoteQuery'))
         + '&level=' + encodeURIComponent(val('memoryLevelFilter'));
  _memoryData = await (await fetch('/api/memory' + qs)).json();
  renderMemoryCenter();
}
function renderMemoryCenter(){
  let r = _memoryData;
  if(!r) return;
  let tiles = document.getElementById('memoryTiles');
  let note = document.getElementById('memoryIntegrityNote');
  let tbody = document.getElementById('memoryNotesTableBody');
  let sel = document.getElementById('memoryLevelFilter');
  // Tier filter options come from memory.MEMORY_LEVELS over the wire, never a
  // hardcoded copy of the tier vocabulary in this page.
  if(sel && sel.options.length <= 1){
    (r.levels||[]).forEach(lv=>{
      let o = document.createElement('option'); o.value = lv; o.textContent = lv; sel.appendChild(o);
    });
  }
  if(!r.available){
    let sd = (r.store&&r.store.store_dir)||'', vp = (r.vault&&r.vault.vault_path)||'';
    tiles.innerHTML = tile(0,'Memory Records');
    note.innerHTML = r.error
      ? '<span class="err">'+r.error.reason+': '+JSON.stringify(r.error.detail)+'</span>'
      : 'No memory record and no knowledge vault in this project yet (looked for <code>'+sd+'</code> and <code>'+vp+'</code>).';
    tbody.innerHTML = '<tr><td style="padding:4px" colspan="8">Nothing to browse yet.</td></tr>';
    return;
  }
  let s = r.store||{}, v = r.vault||{}, ii = s.index_integrity;
  tiles.innerHTML = (r.tiers||[]).map(t=>{
    if(!t.has_local_store){
      // Organizational: the shared Knowledge Center IS its store, so a local
      // count would be a lie in either direction. Show the shared store's
      // real configured state instead.
      let n = t.knowledge_center_configured===true ? 'shared'
            : (t.knowledge_center_configured===false ? 'not cfg' : '?');
      return tile(n, t.level+' (shared KC)');
    }
    return tile(t.record_files==null ? '-' : t.record_files, t.level);
  }).join('') + tile(v.available ? v.note_count : '-', 'Vault Notes');

  let parts = [];
  if(r.error) parts.push('<span class="err">'+r.error.reason+': '+JSON.stringify(r.error.detail)+'</span>');
  if(!s.available){
    parts.push('No local memory store yet (looked for <code>'+s.store_dir+'</code>).');
  } else if(s.error){
    parts.push('<span class="err">'+s.error.reason+': '+JSON.stringify(s.error.detail)+'</span>');
  } else if(ii){
    parts.push('Store <code>'+s.store_dir+'</code>: '+ii.record_file_count+' record file(s), '
      + ii.index_row_count+' index row(s) -- '
      + (ii.ok
          ? '<span class="ok">files and search index agree</span>'
          : '<span class="err">DRIFT: '+(ii.files_missing_from_index||[]).length
            + ' record file(s) invisible to MemoryRetriever.search(), '
            + (ii.index_rows_without_file||[]).length
            + ' index row(s) with no file. Repair with <code>dv-harness memory doctor</code>.</span>'));
  }
  if(!v.available){
    parts.push('No knowledge vault yet (looked for <code>'+v.vault_path+'</code>).');
  } else {
    parts.push('Vault <code>'+v.vault_path+'</code> via <code>'+v.provider+'</code> ('+v.status+'): '
      + v.note_count+' note(s)'
      + (v.scan_truncated ? ' -- scan capped at '+v.scan_limit+', so this count is a floor' : ''));
    if(v.error) parts.push('<span class="err">'+v.error.reason+': '+JSON.stringify(v.error.detail)+'</span>');
  }
  note.innerHTML = parts.join('<br>');

  tbody.innerHTML = (r.notes||[]).map(n=>{
    // `failure` is the note schema's own title-equivalent field
    // (build_frontmatter_from_memory_record(): the record's title, else its
    // root_cause). Truncated in the cell with the full value on hover, the
    // same drill-down-on-hover convention the AMBA card uses.
    let fm = n.frontmatter||{};
    let failure = String(fm.failure||'');
    let hover = `${failure}\\ncategory: ${fm.category||'-'} | subsystem: ${fm.subsystem||'-'}`
      + ` | tags: ${(fm.tags||[]).join(', ')||'-'} | schema: ${fm.schema_status||'-'}`;
    return `<tr style="border-bottom:1px solid #edf1f5;cursor:pointer" title="${hover.replace(/"/g,'&quot;')}" onclick="showMemoryNote('${n.note_id}')">`
      + `<td style="padding:4px"><code>${n.note_id}</code></td>`
      + `<td style="padding:4px">${failure.length>90 ? failure.slice(0,90)+'...' : failure}</td>`
      + `<td style="padding:4px">${fm.memory_level||''}</td>`
      + `<td style="padding:4px">${fm.protocol||''}</td>`
      + `<td style="padding:4px">${fm.status||''}</td>`
      + `<td style="padding:4px">${fm.confidence||''}</td>`
      + `<td style="padding:4px">${fm.updated||''}</td>`
      + `<td style="padding:4px">${n.path||''}</td></tr>`;
  }).join('') || ('<tr><td style="padding:4px" colspan="8">'
      + (v.available ? 'No vault note matches the current search.'
                     : 'No knowledge vault yet -- nothing to browse.')
      + '</td></tr>');
}
async function showMemoryNote(noteId){
  // Full note body read through the SAME provider.read() the CLI uses -- this
  // page never opens a .md file itself.
  let el = document.getElementById('memoryNoteDetail');
  let r = await (await fetch('/api/memory?note='+encodeURIComponent(noteId))).json();
  let d = r.note_detail;
  el.style.display = 'block';
  if(!d || d.ok === false){
    el.textContent = 'Note not readable: '+noteId+' ('+((d&&d.error)||'NOT_FOUND')+')';
    return;
  }
  el.textContent = '['+d.note_id+'] '+d.path+'\\n\\n'
    + JSON.stringify(d.frontmatter, null, 2) + '\\n\\n' + (d.body||'');
}

async function loadKnowledgeStatus(){
  let r = await (await fetch('/api/knowledge/status')).json();
  document.getElementById('knowledgeStatusResult').textContent = JSON.stringify(r, null, 2);
}

async function loadDbInfo(){
  let r = await (await fetch('/api/knowledge/db-info')).json();
  if(r.error){
    document.getElementById('dbInfoTableBody').innerHTML =
      '<tr><td style="padding:4px" colspan="6">'+r.message+'</td></tr>';
    return;
  }
  let rows = (r.activity||[]).map(a=>
    `<tr style="border-bottom:1px solid #edf1f5"><td style="padding:4px">${fmtTs(a.ts)}</td>`+
    `<td style="padding:4px">${a.action}</td><td style="padding:4px"><code>${a.memory_id}</code></td>`+
    `<td style="padding:4px">${a.category}/${a.protocol}</td><td style="padding:4px">${a.origin_user||''}</td>`+
    `<td style="padding:4px">${a.summary||''}</td></tr>`
  ).join('');
  document.getElementById('dbInfoTableBody').innerHTML = rows || '<tr><td style="padding:4px" colspan="6">No activity yet.</td></tr>';
}

async function loadUserInfo(){
  let r = await (await fetch('/api/user-info')).json();
  let rows = (r.users||[]).map(u=>{
    let last = u.sessions && u.sessions.length ? u.sessions[u.sessions.length-1] : null;
    let lastLabel = last ? (fmtTs(_epochOrIso(last.login_at))+' -&gt; '+fmtTs(_epochOrIso(last.logout_at))) : '';
    return `<tr style="border-bottom:1px solid #edf1f5"><td style="padding:4px">${u.user}</td>`+
      `<td style="padding:4px">${u.session_count}</td><td style="padding:4px">${fmtTs(_epochOrIso(u.first_seen))}</td>`+
      `<td style="padding:4px">${lastLabel}</td></tr>`;
  }).join('');
  document.getElementById('userInfoTableBody').innerHTML = rows || '<tr><td style="padding:4px" colspan="4">No recorded access yet.</td></tr>';
}

let _fsdbReportData = null;
async function loadFsdbReport(){
  let path = val('fsdbPath'), period = val('fsdbPeriod'), hier = val('fsdbHier');
  let resultEl = document.getElementById('fsdbReportResult');
  if(!path){ resultEl.textContent = 'path is required'; return; }
  let qs = 'path='+encodeURIComponent(path)
    +(period?'&period='+encodeURIComponent(period):'')
    +(hier?'&hier='+encodeURIComponent(hier):'');
  let r = await (await fetch('/api/fsdb-report?'+qs)).json();
  _fsdbReportData = r;
  if(!r.ok){
    resultEl.textContent = 'fsdbreport failed: '+(r.error||'unknown error')+(r.detail?(' -- '+JSON.stringify(r.detail)):'');
  } else if(!r.parsed){
    resultEl.textContent = 'ran, but output not recognized as real CSV: '+(r.note||'');
  } else {
    resultEl.textContent = (r.records||[]).length+' record(s), columns: '+(r.fieldnames||[]).join(', ');
  }
  renderFsdbReportTable();
}
function renderFsdbReportTable(){
  // Client-side signal-name filter over already-fetched records -- no
  // re-fetch/re-run of the real fsdbreport binary just to filter.
  let head = document.getElementById('fsdbReportTableHead');
  let tbody = document.getElementById('fsdbReportTableBody');
  let r = _fsdbReportData;
  let fields = (r && r.parsed) ? (r.fieldnames||[]) : [];
  if(!fields.length){
    head.innerHTML = '<tr style="text-align:left;border-bottom:1px solid #d9e1ec"></tr>';
    tbody.innerHTML = '<tr><td style="padding:4px">No parsed records yet -- run fsdbreport above.</td></tr>';
    return;
  }
  head.innerHTML = '<tr style="text-align:left;border-bottom:1px solid #d9e1ec">'+
    fields.map(f=>`<th style="padding:4px">${f}</th>`).join('')+'</tr>';
  // Column names are whatever the real -csv output declared (see fsdb_report.py) --
  // prefer a signal/hierarchy-shaped column for the filter, but fall back to
  // matching any column so the filter still works against an unknown real schema.
  let signalField = fields.find(f=>/signal|hier|name/i.test(f));
  let filterVal = (val('fsdbSignalFilter')||'').toLowerCase();
  let records = r.records||[];
  if(filterVal){
    records = records.filter(rec => signalField
      ? String(rec[signalField]||'').toLowerCase().includes(filterVal)
      : fields.some(f=>String(rec[f]||'').toLowerCase().includes(filterVal)));
  }
  let rows = records.map(rec=>
    '<tr style="border-bottom:1px solid #edf1f5">'+fields.map(f=>`<td style="padding:4px">${rec[f]}</td>`).join('')+'</tr>'
  ).join('');
  tbody.innerHTML = rows || `<tr><td style="padding:4px" colspan="${fields.length}">No records match the current filter.</td></tr>`;
}

function _epochOrIso(v){
  if(v==null) return null;
  if(typeof v === 'number') return v;
  let d = Date.parse(v);
  return isNaN(d) ? null : d/1000;
}

function fmtTs(t){ return t ? new Date(t*1000).toLocaleString() : ''; }

async function loadSessions(){
  let r = await (await fetch('/api/session/list')).json();
  let rows = (r.sessions||[]).map(s=>{
    // session_manifest.json now also carries active_stages (2026-08-29) --
    // show a "(+N branches)" indicator next to current_stage when the saved
    // session was captured mid-fan-out, rather than silently showing only
    // the parked source node as if it were the whole picture.
    let stageLabel = (s.active_stages && s.active_stages.length)
      ? `${s.current_stage||''} (+${s.active_stages.length} branches)`
      : (s.current_stage||'');
    return `<tr style="border-bottom:1px solid #edf1f5"><td style="padding:4px"><code>${s.name}</code></td>`+
    `<td style="padding:4px">${fmtTs(s.saved_at)}</td><td style="padding:4px">${stageLabel}</td>`+
    `<td style="padding:4px">${s.note||''}</td><td style="padding:4px">${s.saved_by||''}</td>`+
    `<td style="padding:4px"><button onclick="restoreSession('${s.name}')">Restore</button></td></tr>`;
  }).join('');
  document.getElementById('sessionTableBody').innerHTML = rows || '<tr><td style="padding:4px" colspan="6">No saved sessions.</td></tr>';
}

async function saveSession(){
  let name = val('sessionSaveName'), note = val('sessionSaveNote');
  let r = await postJSON('/api/session/save', {name: name||undefined, note});
  document.getElementById('sessionSaveResult').textContent =
    r.error ? ('Error: '+r.message) : ('Saved as "'+r.name+'".');
  loadSessions();
}

async function restoreSession(name){
  if(!confirm('Restore session "'+name+'"? The current state will be auto-backed-up first.')) return;
  let r = await postJSON('/api/session/restore', {name});
  document.getElementById('sessionSaveResult').textContent =
    r.error ? ('Error: '+r.message) : ('Restored "'+r.restored+'" (previous state backed up as "'+r.auto_backup+'").');
  loadSessions();
  load();
}

let _stagesLoaded = false;
function fillStageSelects(nodeIds){
  if(_stagesLoaded) return;
  let opts = nodeIds.map(id=>`<option value="${id}">${id}</option>`).join('');
  ['redirectStage','approveStage','correctStage','cosignStage'].forEach(id=>{
    let el = document.getElementById(id);
    if(el) el.innerHTML = opts;
  });
  _stagesLoaded = nodeIds.length > 0;
}

// Change Impact View card. Fetch-once + client-side-render shape, same as
// the Generation Readiness / Design Knowledge cards above -- computes
// nothing itself, only renders change_impact.py's own real, already-computed
// computed_selection.json payload.
let _changeImpactData = null;
async function loadChangeImpact(){
  _changeImpactData = await (await fetch('/api/change-impact')).json();
  renderChangeImpact();
}
function renderChangeImpact(){
  let r = _changeImpactData;
  let tiles = document.getElementById('changeImpactTiles');
  let tbody = document.getElementById('changeImpactTableBody');
  let note = document.getElementById('changeImpactNote');
  if(!r) return;
  if(!r.available || !r.payload){
    tiles.innerHTML = tile('-','No computed change impact');
    tbody.innerHTML = '<tr><td style="padding:4px" colspan="6">'+(r.reason||'unavailable')+'</td></tr>';
    note.textContent = '';
    return;
  }
  let p = r.payload, sel = p.selection || {};
  tiles.innerHTML = [
    tile(p.diff_status||'-','Diff Status'),
    tile((p.changed_files||[]).length,'Changed Files'),
    tile((p.unresolved_files||[]).length,'Unresolved Files'),
    tile(sel.confidence||'-','Confidence'),
    tile(sel.expand_to_full_regression? 'YES':'no','Expand to Full'),
    tile(p.registry_size!=null? p.registry_size:'-','Registry Rows'),
  ].join('');
  tbody.innerHTML = (p.impact_rows||[]).map(row=>{
    let riskClass = row.risk==='HIGH'?'BLOCKED':(row.risk==='MEDIUM'?'PARTIAL':'PASS');
    return `<tr style="border-bottom:1px solid #edf1f5">`+
      `<td style="padding:4px">${row.changed_file}</td>`+
      `<td style="padding:4px">${row.impacted_area}</td>`+
      `<td style="padding:4px" class="${riskClass}">${row.risk}</td>`+
      `<td style="padding:4px">${row.confidence}</td>`+
      `<td style="padding:4px">${row.req_id||''}</td>`+
      `<td style="padding:4px">${row.pattern_id||''}</td></tr>`;
  }).join('') || '<tr><td style="padding:4px" colspan="6">No changed files in this diff.</td></tr>';
  note.innerHTML = 'base_sha: <code>'+(p.base_sha||'-')+'</code> head_sha: <code>'+(p.head_sha||'-')+'</code>'
    + ' change_impact_evidence_id: <code>'+(p.change_impact_evidence_id||'-')+'</code>'
    + (p.diff_detail? ' -- '+p.diff_detail : '');
}

// Minimum Safe Regression View card. Same fetch-once shape -- computes
// nothing itself, only renders regression_tiers.py's own real policy table
// plus (when a tier is active) its own tests_for_tier() resolution.
let _regressionTierData = null;
async function loadRegressionTier(){
  _regressionTierData = await (await fetch('/api/regression-tier')).json();
  renderRegressionTier();
}
function renderRegressionTier(){
  let r = _regressionTierData;
  let tiles = document.getElementById('regressionTierTiles');
  let polBody = document.getElementById('regressionTierPolicyBody');
  let msBody = document.getElementById('regressionTierMinSafeBody');
  let msNote = document.getElementById('regressionTierMinSafeNote');
  if(!r) return;
  if(!r.available){
    tiles.innerHTML = tile('-','Regression Tier');
    polBody.innerHTML = '<tr><td style="padding:4px" colspan="5">'+(r.reason||'unavailable')+'</td></tr>';
    msBody.innerHTML = ''; msNote.textContent = '';
    return;
  }
  let active = r.active_tier;
  let ms = r.minimum_safe_regression;
  tiles.innerHTML = [
    tile(active? active.tier : '(none)','Active Tier'),
    tile(active? active.test_count : '-','Declared Test Count'),
    tile(ms && ms.tests ? ms.tests.length : '-','Minimum Safe Tests'),
  ].join('');
  polBody.innerHTML = Object.keys(r.policies||{}).map(tierName=>{
    let p = r.policies[tierName];
    let classes = (p.full_regression? 'FULL+':'') + (p.selection_classes||[]).join(', ');
    return `<tr style="border-bottom:1px solid #edf1f5">`+
      `<td style="padding:4px">${p.tier}</td>`+
      `<td style="padding:4px">${p.cadence}</td>`+
      `<td style="padding:4px">${p.time_budget_minutes}</td>`+
      `<td style="padding:4px">${p.uvm_fatal_burst_threshold}</td>`+
      `<td style="padding:4px">${classes}</td></tr>`;
  }).join('');
  if(!active){
    msNote.textContent = 'No tiered run currently declared active (.dv-harness/regression/active_tier.json) -- this project uses the flat, pre-existing threshold.';
    msBody.innerHTML = '';
  } else if(!ms || ms.available===false){
    msNote.innerHTML = '<span class="err">'+((ms && ms.reason) || 'minimum-safe regression could not be computed')+'</span>';
    msBody.innerHTML = '';
  } else {
    msNote.innerHTML = 'Minimum safe regression for active tier <code>'+active.tier+'</code> ('
      + (ms.full_regression? 'full pattern universe':'impact-derived selection') + '; '
      + (ms.tests||[]).length + ' pattern(s)):';
    msBody.innerHTML = (ms.tests||[]).map((t,i)=>
      `<tr style="border-bottom:1px solid #edf1f5"><td style="padding:4px">${i+1}</td><td style="padding:4px">${t}</td></tr>`
    ).join('') || '<tr><td style="padding:4px" colspan="2">No patterns selected.</td></tr>';
  }
}

// Dependency / Supply-Chain Governance card. Fetch-once + render, same shape
// as the AMBA cards above -- renders only dependency_supply_chain.py's own
// real analyze_supply_chain() report, never a dashboard-local pin/resolution/
// advisory re-derivation.
let _dependencySupplyChainData = null;
async function loadDependencySupplyChain(){
  _dependencySupplyChainData = await (await fetch('/api/dependency-supply-chain')).json();
  renderDependencySupplyChain();
}
function renderDependencySupplyChain(){
  let r = _dependencySupplyChainData;
  let tiles = document.getElementById('dependencySupplyChainTiles');
  let body = document.getElementById('dependencySupplyChainBody');
  let note = document.getElementById('dependencySupplyChainFindingsNote');
  if(!r) return;
  if(r.error){
    tiles.innerHTML = tile('ERROR','Supply-Chain Governance');
    body.innerHTML = '<tr><td style="padding:4px" colspan="6" class="err">'+r.error.reason+': '+JSON.stringify(r.error.detail)+'</td></tr>';
    note.innerHTML = '';
    return;
  }
  let rep = r.report;
  if(!rep){
    tiles.innerHTML = tile('-','Supply-Chain Governance');
    body.innerHTML = '<tr><td style="padding:4px" colspan="6">No report computed.</td></tr>';
    note.innerHTML = '';
    return;
  }
  let inv = rep.inventory || {};
  let comps = inv.components || [];
  let findings = rep.findings || [];
  let notRun = rep.checks_not_run || [];
  tiles.innerHTML = [
    tile(rep.status,'Status'),
    tile(comps.length,'Components'),
    tile(rep.finding_count!=null? rep.finding_count : findings.length,'Findings'),
    tile(notRun.length,'Checks Not Run'),
  ].join('');
  body.innerHTML = comps.map(c=>{
    let inst = c.installed || {};
    return `<tr style="border-bottom:1px solid #edf1f5">`+
      `<td style="padding:4px">${c.name||'(unnamed)'}</td>`+
      `<td style="padding:4px">${c.ecosystem||''}</td>`+
      `<td style="padding:4px">${c.pin_status||''}</td>`+
      `<td style="padding:4px">${c.declared_as||''}</td>`+
      `<td style="padding:4px">${inst.installed_version||'-'}</td>`+
      `<td style="padding:4px">${inst.resolution||''}</td></tr>`;
  }).join('') || '<tr><td style="padding:4px" colspan="6">No declared components found.</td></tr>';
  let parts = [];
  if(findings.length){
    parts.push('Findings: ' + findings.map(f=>
      `<code>${f.severity||''} ${f.kind||''}</code> (${f.component||f.source_path||'-'}): ${f.detail||''}`
    ).join('; '));
  }
  if(notRun.length){
    parts.push('<span class="err">NOT FULLY CHECKED: '+notRun.join(', ')+' -- this is not a clean security result.</span>');
  }
  note.innerHTML = parts.join('<br>');
}

// VIP Scenario Pattern <-> command.txt Correspondence card. Fetch-once +
// render, same shape as the cards above -- renders only scenario_pattern_
// command_txt_correspondence.py's own real
// analyze_scenario_pattern_command_txt_correspondence() output, never a
// dashboard-local re-derivation of the VIP-scenario-pattern <-> branch_b*
// cross-check. Both inputs (capability report path, command.txt path list)
// are caller-typed since neither has a fixed on-disk convention.
let _scenarioPatternCorrespondenceData = null;
async function loadScenarioPatternCorrespondence(){
  let capReport = (document.getElementById('scenarioPatternCapabilityReportInput').value||'').trim();
  let cmdFilesRaw = (document.getElementById('scenarioPatternCommandFilesInput').value||'').trim();
  let params = new URLSearchParams();
  if(capReport) params.set('capability_report', capReport);
  cmdFilesRaw.split(',').map(s=>s.trim()).filter(Boolean).forEach(f=>params.append('command_file', f));
  _scenarioPatternCorrespondenceData = await (await fetch('/api/scenario-pattern-command-txt-correspondence?'+params.toString())).json();
  renderScenarioPatternCorrespondence();
}
function renderScenarioPatternCorrespondence(){
  let r = _scenarioPatternCorrespondenceData;
  let tiles = document.getElementById('scenarioPatternCorrespondenceTiles');
  let body = document.getElementById('scenarioPatternCorrespondenceBody');
  let note = document.getElementById('scenarioPatternCorrespondenceNote');
  if(!r) return;
  if(r.error){
    tiles.innerHTML = tile('ERROR','Correspondence');
    body.innerHTML = '<tr><td style="padding:4px" colspan="5" class="err">'+r.error.reason+': '+JSON.stringify(r.error.detail)+'</td></tr>';
    note.innerHTML = '';
    return;
  }
  let rep = r.report;
  if(!r.available || !rep){
    tiles.innerHTML = tile('-','Correspondence');
    body.innerHTML = '<tr><td style="padding:4px" colspan="5">Enter a capability report path (and optionally command.txt path(s)) above, then Refresh.</td></tr>';
    note.innerHTML = '';
    return;
  }
  tiles.innerHTML = [
    tile(rep.status,'Status'),
    tile(rep.total_declared_patterns,'Declared Patterns'),
    tile(rep.total_used_patterns,'Used'),
    tile(rep.total_unused_patterns,'Unused'),
    tile(rep.total_branch_b_usages,'branch_b* Usages'),
    tile(rep.total_confirmed_usages,'Confirmed'),
    tile(rep.total_unresolved_usages,'Unresolved'),
  ].join('');
  body.innerHTML = (rep.branch_b_usages||[]).map(u=>
    `<tr style="border-bottom:1px solid #edf1f5"><td style="padding:4px">${u.command_name||''}</td>`+
    `<td style="padding:4px">${u.status||''}</td><td style="padding:4px">${u.matched_class_name||'-'}</td>`+
    `<td style="padding:4px">${u.match_kind||'-'}</td><td style="padding:4px">${u.evidence||'-'}</td></tr>`
  ).join('') || '<tr><td style="padding:4px" colspan="5">No branch_b* usages found.</td></tr>';
  let parts = [];
  if(rep.reason) parts.push('<span class="err">'+rep.reason+'</span>');
  if((rep.unreadable_command_files||[]).length){
    parts.push('<span class="err">Unreadable command files: '+rep.unreadable_command_files.map(f=>f.path+': '+f.reason).join('; ')+'</span>');
  }
  note.innerHTML = parts.join('<br>');
}

// Intake Events card. Fetch-once + render, same shape as the cards above --
// renders only intake_events.py's own real read_intake_events() output,
// never a dashboard-local re-parse of events.jsonl or a re-derivation of the
// fixed 18-event taxonomy.
let _intakeEventsData = null;
async function loadIntakeEvents(){
  _intakeEventsData = await (await fetch('/api/intake-events')).json();
  renderIntakeEvents();
}
function renderIntakeEvents(){
  let r = _intakeEventsData;
  let tiles = document.getElementById('intakeEventsTiles');
  let body = document.getElementById('intakeEventsBody');
  let note = document.getElementById('intakeEventsNote');
  if(!r) return;
  if(r.error){
    tiles.innerHTML = tile('ERROR','Intake Events');
    body.innerHTML = '<tr><td style="padding:4px" colspan="3" class="err">'+r.error.reason+': '+JSON.stringify(r.error.detail)+'</td></tr>';
    note.innerHTML = '';
    return;
  }
  let events = r.events || [];
  let taxonomy = r.taxonomy || [];
  let scan = r.scan || {};
  let seen = new Set(events.map(e=>e.event));
  tiles.innerHTML = [
    tile(events.length,'Events Recorded'),
    tile(seen.size + '/' + taxonomy.length,'Distinct INTAKE_* Names Seen'),
    tile(scan.lines_scanned!=null? scan.lines_scanned : '-','events.jsonl Lines Scanned'),
  ].join('');
  body.innerHTML = events.slice().reverse().map(e=>{
    let payload = Object.assign({}, e);
    delete payload.ts; delete payload.event;
    return `<tr style="border-bottom:1px solid #edf1f5">`+
      `<td style="padding:4px">${e.ts||''}</td>`+
      `<td style="padding:4px"><code>${e.event||''}</code></td>`+
      `<td style="padding:4px;font-family:monospace;font-size:11px">${JSON.stringify(payload)}</td></tr>`;
  }).join('') || '<tr><td style="padding:4px" colspan="3">No INTAKE_* events recorded yet -- emission is opt-in (a caller must pass a real <code>store=</code> into verification_intake_contract.py/intake_state.py).</td></tr>';
  note.innerHTML = scan.scan_truncated? '<span class="err">events.jsonl scan truncated -- only the trailing window was searched.</span>' : '';
}

// Pattern Runtime State Machine card. Fetch-once + render, same shape as the
// cards above -- renders only pattern_runtime_state_machine.py's own real
// execute_verb() output, never a dashboard-local re-derivation of the state
// machine or its legal-transition table.
let _patternRuntimeStateData = null;
async function loadPatternRuntimeState(){
  _patternRuntimeStateData = await (await fetch('/api/pattern-runtime-state')).json();
  renderPatternRuntimeState();
}
function renderPatternRuntimeState(){
  let r = _patternRuntimeStateData;
  let tiles = document.getElementById('patternRuntimeStateTiles');
  let body = document.getElementById('patternRuntimeStateBody');
  let note = document.getElementById('patternRuntimeStateNote');
  if(!r) return;
  if(r.error){
    tiles.innerHTML = tile('ERROR','Pattern Runtime State');
    body.innerHTML = '<tr><td style="padding:4px" colspan="6" class="err">'+r.error.reason+': '+JSON.stringify(r.error.detail)+'</td></tr>';
    note.innerHTML = '';
    return;
  }
  let records = r.records || [];
  let terminal = records.filter(rec=>{
    let s = rec.state;
    return s==='PASS'||s==='FAIL'||s==='TIMEOUT'||s==='BLOCKED'||s==='CANCELLED';
  });
  tiles.innerHTML = [
    tile(records.length,'Pattern Records'),
    tile(terminal.length,'Terminal'),
    tile(records.length-terminal.length,'In Progress'),
  ].join('');
  body.innerHTML = records.map(rec=>{
    let hist = rec.history || [];
    let isTerm = (rec.state==='PASS'||rec.state==='FAIL'||rec.state==='TIMEOUT'||rec.state==='BLOCKED'||rec.state==='CANCELLED');
    return `<tr style="border-bottom:1px solid #edf1f5">`+
      `<td style="padding:4px">${rec.pattern_id||''}</td>`+
      `<td style="padding:4px">${rec.protocol||'-'}</td>`+
      `<td style="padding:4px"><code>${rec.state||''}</code></td>`+
      `<td style="padding:4px">${isTerm?'yes':'no'}</td>`+
      `<td style="padding:4px">${hist.length}</td>`+
      `<td style="padding:4px">${rec.created_at||''}</td></tr>`;
  }).join('') || '<tr><td style="padding:4px" colspan="6">No pattern runtime records tracked yet -- persistence is opt-in (a caller must call advance_pattern_state()/save_records() itself).</td></tr>';
  let states = r.states || [];
  note.innerHTML = states.length? ('Legal transitions: ' + states.map(s=>
    `<code>${s.state}</code>${s.terminal==='yes'?' (terminal)':' &rarr; '+(s.legal_transitions||'')}`
  ).join('; ')) : '';
}

// Protocol Selector card (GUI-02). Fetch-once + render, same shape as the
// cards above -- renders only protocol_router.py's own real
// resolve_protocol() output (called three times over one declared evidence
// document: user_declared, auto_detected, authoritative), never a
// dashboard-local re-derivation of protocol-router's own normalization or
// tie-break logic.
let _protocolSelectorData = null;
async function loadProtocolSelector(){
  _protocolSelectorData = await (await fetch('/api/protocol-selector')).json();
  renderProtocolSelector();
}
function renderProtocolSelector(){
  let r = _protocolSelectorData;
  let tiles = document.getElementById('protocolSelectorTiles');
  let body = document.getElementById('protocolSelectorBody');
  let note = document.getElementById('protocolSelectorNote');
  if(!r) return;
  if(r.error){
    tiles.innerHTML = tile('ERROR','Protocol Selector');
    body.innerHTML = '<tr><td style="padding:4px" colspan="4" class="err">'+r.error.reason+': '+JSON.stringify(r.error.detail)+'</td></tr>';
    note.innerHTML = '';
    return;
  }
  if(!r.available){
    tiles.innerHTML = tile('NO EVIDENCE','Protocol Selector');
    body.innerHTML = '<tr><td style="padding:4px" colspan="4">No protocol-selector evidence declared yet at '+(r.inputs_path||'')+' -- never fabricated.</td></tr>';
    note.innerHTML = '';
    return;
  }
  let ud = r.user_declared, ad = r.auto_detected, au = r.authoritative;
  tiles.innerHTML = [
    tile(ud? (ud.display_name||'UNRESOLVED') : '-','User-Declared'),
    tile(ad? (ad.display_name||'UNRESOLVED') : '-','Auto-Detected'),
    tile(au? (au.display_name||'UNRESOLVED') : '-','Authoritative'),
    tile(r.confidence||'-','Confidence'),
    tile(r.conflict?'YES':'no','Conflict'),
  ].join('');
  let rows = [
    ['User-Declared', ud],
    ['Auto-Detected', ad],
    ['Authoritative (protocol-router)', au],
  ];
  body.innerHTML = rows.map(function(pair){
    let label = pair[0], res = pair[1];
    if(!res){
      return '<tr style="border-bottom:1px solid #edf1f5"><td style="padding:4px">'+label+'</td>'+
        '<td style="padding:4px">-</td><td style="padding:4px">-</td><td style="padding:4px">not declared</td></tr>';
    }
    return '<tr style="border-bottom:1px solid #edf1f5">'+
      '<td style="padding:4px">'+label+'</td>'+
      '<td style="padding:4px">'+(res.display_name||'<span class="err">UNRESOLVED</span>')+'</td>'+
      '<td style="padding:4px">'+(res.matched_field||'-')+'</td>'+
      '<td style="padding:4px">'+(res.evidence||res.reason||'')+'</td></tr>';
  }).join('');
  note.innerHTML = r.conflict? '<span class="err">Conflict: user-declared and auto-detected protocols disagree -- protocol-router\\'s own tie-break order (Authoritative row above) decides; this card only surfaces the disagreement, it never arbitrates it.</span>' : '';
}

// Intake Baseline card. Fetch-once + render, same shape as the two cards
// above -- renders only intake_baseline.py's own real list_intake_freezes()/
// evaluate_all_intake_freezes() output, never a dashboard-local
// re-derivation of a freeze's status.
let _intakeBaselineData = null;
async function loadIntakeBaseline(){
  _intakeBaselineData = await (await fetch('/api/intake-baseline')).json();
  renderIntakeBaseline();
}
function renderIntakeBaseline(){
  let r = _intakeBaselineData;
  let tiles = document.getElementById('intakeBaselineTiles');
  let body = document.getElementById('intakeBaselineBody');
  let note = document.getElementById('intakeBaselineNote');
  if(!r) return;
  if(r.error){
    tiles.innerHTML = tile('ERROR','Intake Baseline');
    body.innerHTML = '<tr><td style="padding:4px" colspan="6" class="err">'+r.error.reason+': '+JSON.stringify(r.error.detail)+'</td></tr>';
    note.innerHTML = '';
    return;
  }
  let freezes = r.freezes || [];
  let evalu = r.evaluation;
  tiles.innerHTML = [
    tile(freezes.length,'Recorded Freezes'),
    tile(r.current_facts_supplied? 'yes':'no','Current Facts Supplied'),
    tile(evalu? evalu.status : '-','Re-Evaluation Status'),
  ].join('');
  body.innerHTML = freezes.slice().reverse().map(f=>{
    let ev = (evalu && evalu.freezes || []).find(e=>e.freeze_id===f.freeze_id);
    return `<tr style="border-bottom:1px solid #edf1f5">`+
      `<td style="padding:4px"><code>${f.freeze_id||''}</code></td>`+
      `<td style="padding:4px">${f.frozen_by||''}</td>`+
      `<td style="padding:4px">${f.frozen_at||''}</td>`+
      `<td style="padding:4px">${ev? ('<code>'+ev.status+'</code>') : '(not evaluated -- no current facts supplied)'}</td>`+
      `<td style="padding:4px">${ev? ev.invalidating_count : '-'}</td>`+
      `<td style="padding:4px">${ev? ev.indeterminate_count : '-'}</td></tr>`;
  }).join('') || '<tr><td style="padding:4px" colspan="6">No intake freezes recorded yet -- a caller must call intake_baseline.freeze_intake_baseline() itself.</td></tr>';
  note.innerHTML = r.current_facts_supplied
    ? ('Evaluated against: <code>'+r.current_facts_path+'</code>')
    : ('No current-facts document found at <code>'+(r.current_facts_path||'')+'</code> -- freezes are listed but never re-evaluated against fabricated facts.');
}

// Pattern Coverage Contribution card. Button-triggered (like the FSDB Report
// card above), never auto-loaded on page load, since pattern_coverage_
// contribution.py's own real compute_pattern_coverage_contribution() needs a
// real ?pattern= and a real ?attribution= file path this card cannot supply
// on its own -- see _read_pattern_coverage_contribution_state()'s comment.
let _patternCoverageContributionData = null;
async function loadPatternCoverageContribution(){
  let pattern = val('pccPattern'), attribution = val('pccAttribution'), crossDefs = val('pccCrossDefs');
  let note = document.getElementById('patternCoverageContributionNote');
  if(!pattern){ note.textContent = 'pattern is required'; return; }
  let qs = 'pattern='+encodeURIComponent(pattern)
    +(attribution?'&attribution='+encodeURIComponent(attribution):'')
    +(crossDefs?'&cross_definitions='+encodeURIComponent(crossDefs):'');
  _patternCoverageContributionData = await (await fetch('/api/pattern-coverage-contribution?'+qs)).json();
  renderPatternCoverageContribution();
}
function renderPatternCoverageContribution(){
  let r = _patternCoverageContributionData;
  let tiles = document.getElementById('patternCoverageContributionTiles');
  let body = document.getElementById('patternCoverageContributionBody');
  let note = document.getElementById('patternCoverageContributionNote');
  if(!r) return;
  if(!r.available || !r.report){
    tiles.innerHTML = tile(r.error? r.error.reason : 'UNAVAILABLE', 'Pattern Coverage Contribution');
    body.innerHTML = '<tr><td style="padding:4px" colspan="5" class="err">'+
      (r.error? (r.error.reason+': '+JSON.stringify(r.error.detail)) : 'not available')+'</td></tr>';
    note.innerHTML = '';
    return;
  }
  let rep = r.report;
  let cov = rep.coverage || {};
  let rt = rep.runtime || {};
  let fl = rep.failures || {};
  tiles.innerHTML = [
    tile(rep.status,'Overall Status'),
    tile(cov.new_bins_hit!=null? cov.new_bins_hit : '-','New Bins Hit'),
    tile(cov.new_crosses_hit!=null? cov.new_crosses_hit : '-','New Meaningful Crosses'),
    tile(cov.coverage_delta_percent!=null? cov.coverage_delta_percent+'%' : '-','Coverage Delta'),
    tile(rt.total_seconds!=null? rt.total_seconds+'s' : '-','Total Runtime'),
    tile(fl.failed_job_count!=null? fl.failed_job_count : '-','Failed Jobs'),
    tile(rep.cost? rep.cost.status : '-','Cost'),
  ].join('');
  let rows = cov.category_breakdown || [];
  body.innerHTML = rows.map(c=>
    `<tr style="border-bottom:1px solid #edf1f5">`+
    `<td style="padding:4px">${c.category_name||''}${c.is_cross?' (cross: '+(c.cross_verdict||'')+')':''}</td>`+
    `<td style="padding:4px">${c.before_bins_hit!=null?c.before_bins_hit:'-'}</td>`+
    `<td style="padding:4px">${c.after_bins_hit!=null?c.after_bins_hit:'-'}</td>`+
    `<td style="padding:4px">${c.bins_total!=null?c.bins_total:'-'}</td>`+
    `<td style="padding:4px">${c.new_bins_hit!=null?c.new_bins_hit:'-'}</td></tr>`
  ).join('') || '<tr><td style="padding:4px" colspan="5">'+(cov.reason||'No category breakdown available.')+'</td></tr>';
  let ev = (rep.evidence||[]).map(e=>e.source+': '+e.status).join('; ');
  let regressed = (cov.regressed_categories||[]);
  note.innerHTML = 'Evidence: '+ev
    + (regressed.length? (' -- <span class="err">regressed categories: '+regressed.join(', ')+'</span>') : '')
    + (rep.cost? (' -- cost: '+rep.cost.reason) : '');
}

// Build/Remote/LSF Intake card. Fetch-once + render, same shape as the cards
// above -- renders only build_remote_lsf_intake.py's own real
// fields_from_preflight()/evaluate_build_remote_lsf_readiness() output, from
// an already-declared PreflightResult/TransportDecision JSON document on
// disk. NEVER triggers a live preflight probe from this page.
let _buildRemoteLsfIntakeData = null;
async function loadBuildRemoteLsfIntake(){
  _buildRemoteLsfIntakeData = await (await fetch('/api/build-remote-lsf-intake')).json();
  renderBuildRemoteLsfIntake();
}
function renderBuildRemoteLsfIntake(){
  let r = _buildRemoteLsfIntakeData;
  let tiles = document.getElementById('buildRemoteLsfIntakeTiles');
  let body = document.getElementById('buildRemoteLsfIntakeBody');
  let note = document.getElementById('buildRemoteLsfIntakeNote');
  if(!r) return;
  if(r.error){
    tiles.innerHTML = tile('ERROR','Build/Remote/LSF Intake');
    body.innerHTML = '<tr><td style="padding:4px" colspan="5" class="err">'+r.error.reason+': '+JSON.stringify(r.error.detail)+'</td></tr>';
    note.innerHTML = '';
    return;
  }
  if(!r.available || !r.fields){
    tiles.innerHTML = tile('NOT AVAILABLE','Build/Remote/LSF Intake');
    body.innerHTML = '<tr><td style="padding:4px" colspan="5">No preflight_result.json declared at <code>'+(r.inputs_path||'')+'</code> -- this card never invokes a live probe on its own; run a real preflight elsewhere first, then write its result there.</td></tr>';
    note.innerHTML = '';
    return;
  }
  let fields = r.fields || [];
  let readiness = r.readiness || {};
  tiles.innerHTML = [
    tile(readiness.ready? 'yes':'no','Ready'),
    tile(readiness.status||'-','Category Status'),
    tile(fields.filter(f=>f.status==='BLOCKED').length,'Blocked Fields'),
  ].join('');
  body.innerHTML = fields.map(f=>
    `<tr style="border-bottom:1px solid #edf1f5">`+
    `<td style="padding:4px">${f.field||''}</td>`+
    `<td style="padding:4px"><code>${f.status||''}</code></td>`+
    `<td style="padding:4px">${f.confidence||''}</td>`+
    `<td style="padding:4px">${f.value!=null?f.value:'-'}</td>`+
    `<td style="padding:4px">${f.reason||''}</td></tr>`
  ).join('') || '<tr><td style="padding:4px" colspan="5">No fields.</td></tr>';
  note.innerHTML = 'Evaluated against: <code>'+(r.inputs_path||'')+'</code>';
}

// Memory Quality Policy card. Fetch-once + render, same shape as the cards
// above -- renders only memory_quality_policy.py's own real
// evaluate_memory_quality() report (never apply()), never a dashboard-local
// re-derivation of the age/never-confirmed/duplicate decision logic.
let _memoryQualityPolicyData = null;
async function loadMemoryQualityPolicy(){
  _memoryQualityPolicyData = await (await fetch('/api/memory-quality-policy')).json();
  renderMemoryQualityPolicy();
}
function renderMemoryQualityPolicy(){
  let r = _memoryQualityPolicyData;
  let tiles = document.getElementById('memoryQualityPolicyTiles');
  let body = document.getElementById('memoryQualityPolicyBody');
  let note = document.getElementById('memoryQualityPolicyNote');
  if(!r) return;
  if(r.error){
    tiles.innerHTML = tile('ERROR','Memory Quality Policy');
    body.innerHTML = '<tr><td style="padding:4px" colspan="5" class="err">'+r.error.reason+': '+JSON.stringify(r.error.detail)+'</td></tr>';
    note.innerHTML = '';
    return;
  }
  let rep = r.report;
  if(!rep || rep.status === 'NOT_AVAILABLE'){
    tiles.innerHTML = tile('NOT_AVAILABLE','Memory Quality Policy');
    body.innerHTML = '<tr><td style="padding:4px" colspan="5">No local Memory store on this project yet'+(rep&&rep.reason? (' -- '+rep.reason) : '')+'.</td></tr>';
    note.innerHTML = '';
    return;
  }
  let flagStale = rep.flag_stale || [];
  let deprecate = rep.deprecate || [];
  let supersede = rep.supersede || [];
  let policy = rep.policy || {};
  tiles.innerHTML = [
    tile(rep.status,'Status'),
    tile(rep.total_recommended!=null? rep.total_recommended : (flagStale.length+deprecate.length+supersede.length),'Total Recommended'),
    tile(flagStale.length,'Flag Stale'),
    tile(deprecate.length,'Deprecate'),
    tile(supersede.length,'Supersede'),
  ].join('');
  let rows = []
    .concat(flagStale.map(d=>Object.assign({action:'FLAG_STALE'},d)))
    .concat(deprecate.map(d=>Object.assign({action:'DEPRECATE'},d)))
    .concat(supersede.map(d=>Object.assign({action:'SUPERSEDE'},d)));
  body.innerHTML = rows.map(d=>{
    return `<tr style="border-bottom:1px solid #edf1f5">`+
      `<td style="padding:4px"><code>${d.action||''}</code></td>`+
      `<td style="padding:4px">${d.memory_id||''}</td>`+
      `<td style="padding:4px">${d.level||''}</td>`+
      `<td style="padding:4px">${d.status||''}</td>`+
      `<td style="padding:4px">${d.reason||''}</td></tr>`;
  }).join('') || '<tr><td style="padding:4px" colspan="5">No records recommended for retirement -- store is CLEAN under the current policy.</td></tr>';
  note.innerHTML = policy.stale_after_days!=null?
    ('Policy (source: <code>'+(policy.source||'')+'</code>): stale after '+policy.stale_after_days+'d, deprecate after '+policy.deprecate_after_days+'d.') : '';
}

// Notification Center card. Reuses escalation_notify.py's own configuration
// shape and harness_status.py's own persisted change-only transition
// history -- never a new alerting/notification-log mechanism.
let _notificationCenterData = null;
async function loadNotificationCenter(){
  _notificationCenterData = await (await fetch('/api/notifications')).json();
  renderNotificationCenter();
}
function renderNotificationCenter(){
  let r = _notificationCenterData;
  let tiles = document.getElementById('notificationCenterTiles');
  let tbody = document.getElementById('notificationCenterTableBody');
  let note = document.getElementById('notificationCenterNote');
  if(!r) return;
  let ec = r.escalation_config || {};
  tiles.innerHTML = [
    tile(ec.enabled? 'ON':'OFF','Escalation Enabled'),
    tile(ec.transport_configured? 'YES':'no','Transport Configured'),
    tile(r.active_uvm_fatal_burst_threshold!=null? r.active_uvm_fatal_burst_threshold:'-','Active Fatal Threshold'),
    tile((r.notifications||[]).length,'Real Transitions'),
  ].join('');
  tbody.innerHTML = (r.notifications||[]).map(n=>{
    return `<tr style="border-bottom:1px solid #edf1f5">`+
      `<td style="padding:4px">${n.ts||''}</td>`+
      `<td style="padding:4px">${n.previous_state||''}</td>`+
      `<td style="padding:4px">${n.harness_state||''}</td>`+
      `<td style="padding:4px">${n.signoff_state||''}</td>`+
      `<td style="padding:4px">${n.trigger||''}</td></tr>`;
  }).join('') || '<tr><td style="padding:4px" colspan="5">No real state-changing notification recorded yet.</td></tr>';
  note.textContent = r.history_available ? '' :
    (r.notifications_reason || 'No HARNESS_STATUS_SNAPSHOT history recorded yet -- run `dv-harness status --record` to populate it.');
}

// GUI Observability panel. This dashboard PROCESS's own self-measured route
// latency (recorded by Handler._send() on the Python side) plus the real
// events.jsonl backlog/staleness reused from loop_telemetry.read_events().
let _observabilityData = null;
async function loadObservability(){
  _observabilityData = await (await fetch('/api/observability')).json();
  renderObservability();
}
function renderObservability(){
  let r = _observabilityData;
  let tiles = document.getElementById('observabilityTiles');
  let tbody = document.getElementById('observabilityRouteBody');
  let note = document.getElementById('observabilityNote');
  if(!r) return;
  let eb = r.events_backlog || {};
  tiles.innerHTML = [
    tile(r.process_uptime_seconds!=null? r.process_uptime_seconds+'s':'-','Process Uptime'),
    tile(eb.total_lines!=null? eb.total_lines:'-','events.jsonl Lines'),
    tile(eb.staleness_seconds!=null? eb.staleness_seconds+'s':'-','Last Event Age'),
    tile((r.routes||[]).length,'Routes Measured'),
  ].join('');
  tbody.innerHTML = (r.routes||[]).map(row=>{
    return `<tr style="border-bottom:1px solid #edf1f5">`+
      `<td style="padding:4px">${row.route}</td>`+
      `<td style="padding:4px">${row.sample_count}</td>`+
      `<td style="padding:4px">${row.last_ms}</td>`+
      `<td style="padding:4px">${row.avg_ms}</td>`+
      `<td style="padding:4px">${row.p50_ms}</td>`+
      `<td style="padding:4px">${row.max_ms}</td></tr>`;
  }).join('') || '<tr><td style="padding:4px" colspan="6">No route latency samples yet -- reload the page.</td></tr>';
  note.innerHTML = eb.available===false ? ('<span class="err">'+(eb.reason||'events.jsonl unavailable')+'</span>')
    : ('events.jsonl scan truncated: ' + (eb.scan_truncated? 'yes':'no'));
}

async function load(){
 loadGlobalStatusBar();
 let s=await (await fetch('/api/state')).json();
 document.getElementById('tiles').innerHTML=[
   tile(s.project||'-','Project'), tile(s.scope||'-','Scope'),
   tile(s.current_stage||'-','Current Stage'), tile(s.overall_status||'-','Status'),
   tile(s.git_sha? s.git_sha.slice(0,8):'-','Git SHA'), tile(s.server_sha? s.server_sha.slice(0,8):'-','Server SHA'),
   tile(s.git_sha && s.server_sha ? (s.git_sha===s.server_sha?'YES':'NO') : '-', 'SHA Match'),
   tile(s.execution_mode||'-','Execution Mode'),
   tile((s.overall_progress_percent!=null? s.overall_progress_percent:0)+'%','Overall Progress'),
   tile(s.coverage_credit_percent!=null? (s.coverage_credit_percent+'%') : '-','Coverage')
 ].join('');
 document.getElementById('progressbar').style.width=(s.overall_progress_percent||0)+'%';
 renderLastTransitionBanner(s.last_transition);

 // Control-plane visibility: a paused/taken-over/constrained session must
 // not look identical to an idle one from the browser alone.
 document.getElementById('cptiles').innerHTML=[
   tile(s.paused? ('YES'+(s.paused_reason? ' - '+s.paused_reason:'')) : 'no','Paused'),
   tile(s.takeover_active? ('YES on '+s.takeover_stage) : 'no','Takeover'),
   tile(s.active_constraint_count||0,'Active Constraints'),
   tile(s.dv_review_cosign_enforced? 'ON':'OFF','DV-Review Co-sign Enforced'),
 ].join('');
 let enforceEl = document.getElementById('cosignEnforceToggle');
 if (enforceEl) enforceEl.checked = !!s.dv_review_cosign_enforced;
 document.getElementById('constraintList').innerHTML = (s.constraints||[]).length
   ? 'Constraints: ' + s.constraints.map(c=>`<code>${c.id}</code>: ${c.text}`).join(' | ')
   : 'No active constraints.';

 // Why: real per-run blocking_reason/gate_verdict/evidence for the current
 // stage, not the static generic explainer -- plus the stage completion
 // percent and entry/exit evidence checklist (checklistBlock()/
 // stageWhyHTML() above), so a gap here names the exact missing item
 // instead of requiring a raw-JSON read.
 let d = s.current_stage_detail;
 document.getElementById('stageWhy').innerHTML = stageWhyHTML(d);

 // Setup gate: show the setup form until the project has been configured
 // from this dashboard (POST /api/setup); hide it once configured.
 document.getElementById('setupCard').style.display = s.configured ? 'none' : '';

 // Intake Uploads: real files on disk under .dv-harness/uploads/<category>/,
 // never a fabricated placeholder -- a category with zero files shows
 // "(none yet)".
 let ufLabels = {spec:'Spec', rtl:'RTL / Interface', command_txt:'command.txt',
   vip_reference:'VIP Reference', de_sim:'DE Local Sim'};
 let uf = s.uploaded_files || {};
 document.getElementById('uploadedFilesList').innerHTML = Object.keys(ufLabels).map(cat=>{
   let files = uf[cat] || [];
   let list = files.length
     ? files.map(f=>`<code>${f.filename}</code> (${f.bytes}B)`).join(', ')
     : '(none yet)';
   return `<div><b>${ufLabels[cat]}:</b> ${list}</div>`;
 }).join('');

 // Start controls: disabled until configured, disabled again while a run
 // is active (module-level in-flight flag from POST /api/start).
 let canStart = !!s.configured && !s.running;
 document.getElementById('startLoopBtn').disabled = !canStart;
 document.getElementById('startSingleBtn').disabled = !canStart;
 document.getElementById('runStatusNote').textContent = s.running
   ? 'Harness is currently running in the background...'
   : (s.configured ? '' : 'Save Setup above before the harness can be started from this dashboard.');

 let l=await (await fetch('/api/lsf')).json();
 document.getElementById('lsftiles').innerHTML=[
   tile(l.total,'Total'), tile(l.PEND||0,'PEND'), tile(l.RUN||0,'RUN'),
   tile(l.DONE||0,'DONE'), tile(l.EXIT||0,'EXIT'), tile(l.pass_confirmed||0,'PASS'),
   tile(l.fail_confirmed||0,'FAIL'), tile(l.early_kill||0,'EARLY KILL'),
   tile(l.first_failure? ('#'+l.first_failure.job_id) : '-','First Failure'),
   tile(l.first_failure? (l.first_failure.timestamp||'-') : '-','First Failure Time')
 ].join('');

 document.getElementById('findtiles').innerHTML=[
   tile(s.findings_total||0,'Total'), tile(s.findings_open||0,'Open'), tile(s.findings_closed||0,'Closed')
 ].join('');

 let fa = s.failure_attribution;
 document.getElementById('attrtiles').innerHTML = fa ? [
   tile(fa.verdict,'Verdict'),
   tile(fa.first_bad_event ? fa.first_bad_event.stage : '-','First Bad Event Stage')
 ].join('') : tile('-','Verdict');

 let atRisk = s.paused || s.takeover_active;
 document.getElementById('healthtiles').innerHTML=[
   tile(s.current_stage||'-','Current Stage'),
   tile((s.overall_progress_percent!=null?s.overall_progress_percent+'%':'-'),'Overall Progress'),
   tile((s.coverage_credit_percent!=null?s.coverage_credit_percent+'%':'-'),'Coverage Credit'),
   tile(s.findings_open||0,'Open Findings'),
   tile(s.dv_review_pending_count||0,'Awaiting Sign-off'),
   tile(atRisk?('&#9888; '+(s.paused?'PAUSED':'TAKEOVER')):'OK','Flow Status'),
   tile(s.active_constraint_count||0,'Active Constraints'),
   // Graph-level parallel fan-out/join (2026-08-29): HarnessState.active_stages
   // is empty except during a live fan-out (e.g. PROTOCOL_CAPABILITY's
   // ANALYSIS_G1 branches) -- current_stage alone stays on the fan-out's
   // parked source node throughout, so this is the one place a viewer can
   // actually see the concurrently-running branches by name.
   tile((s.active_stages&&s.active_stages.length) ? (s.active_stages.length+' branches active: '+s.active_stages.join(', ')) : 'no active fan-out','Parallel Fan-out')
 ].join('');

 document.getElementById('dvtiles').innerHTML=[
   tile(s.dv_review_pending_count||0,'Awaiting DV Sign-off')
 ].join('');
 document.getElementById('dvfields').innerHTML=(s.dv_review_pending_fields||[]).map(f=>`<li>${f}</li>`).join('');

 // Blackboard Evidence: honest gap card -- real current topic list, no
 // fabricated unified "evidence" store.
 let bbTopics = s.blackboard_topics||[];
 document.getElementById('blackboardEvidenceNote').textContent = bbTopics.includes('evidence')
   ? 'An "evidence" blackboard topic exists.'
   : 'Evidence is currently distributed across: Audit Trail, Findings, DV Review, Attribution cards on this page (no single unified Evidence blackboard topic exists yet).';
 document.getElementById('blackboardTopicsList').innerHTML = bbTopics.map(t=>`<code>${t}</code>`).join(', ') || '(none)';

 // Hypothesis & Review: reuses fa/s.dv_review_pending_count already computed
 // above -- no new backend logic, just a labeled pointer.
 document.getElementById('hyprevtiles').innerHTML=[
   tile(fa? fa.verdict : '-','Hypothesis (Attribution Verdict)'),
   tile(s.dv_review_pending_count||0,'Pending Review (Co-sign)')
 ].join('');

 // Qualified Conclusion: composes gates.py's per-stage gate verdict with
 // inference.py's independently-recomputed confidence (see
 // dv_harness/qualified_conclusion.py) -- is_qualified is already computed
 // server-side, this only labels it. False is deliberately labeled "AI
 // Opinion", never "FAIL"/"LOW" -- it's a legitimate, ordinary result, not
 // an error.
 let qc = s.qualified_conclusion;
 document.getElementById('qualtiles').innerHTML = qc ? [
   tile(qc.is_qualified ? 'Qualified Conclusion' : 'AI Opinion (not yet qualified)', 'Verdict'),
   tile(qc.gate_verdict || '-', 'Gate Verdict'),
   tile((qc.inference_confidence && qc.inference_confidence.level) || '-', 'Confidence'),
   tile(qc.hypothesis || '-', 'Hypothesis'),
 ].join('') : tile('-', 'No qualified conclusion yet (RE_AUDIT has not produced one)');

 // Protocols: real registered protocols, each tile a real click target
 // (selectProtocol()) that fills the Goal field POST /api/start actually
 // reads -- not a static reference-only div. Each tile carries BOTH statuses:
 // capability_status (what protocol-specific generation code exists, classed
 // cap-generic-only when it is only the protocol-agnostic skeleton) and
 // qualification_status (how far it has been proven). Showing one without the
 // other is what let 11 identical BUILDER_AVAILABLE tiles read as equal
 // readiness -- see protocol_capability.py.
 document.getElementById('protocoltiles').innerHTML = (s.protocol_registry||[]).length
   ? s.protocol_registry.map(p=>{
       let cap = p.capability_status||'-';
       let capCls = cap==='GENERIC_SKELETON_ONLY' ? 'cap-generic-only'
                  : (cap==='DUT_PROVEN' ? 'cap-dut-proven' : 'cap-model');
       let model = p.protocol_model_generator||'NONE';
       return `<div class="tile protoTile" title="protocol model generator: ${model}" onclick="selectProtocol(this,'${String(p.name).replace(/'/g,"\\'")}')"><div class="n">${p.name}</div><div class="l ${capCls}">${cap}</div><div class="l">${p.qualification_status}</div></div>`;
     }).join('')
   : tile('-','No protocols registered');

 // Environment Mode Router: highlights whichever mode key matches
 // environment_mode_selected, from _environment_mode_selected() --
 // PROJECT_MODEL now mandates an environment_mode_selection evidence block
 // (gates.STAGE_GATES["PROJECT_MODEL"]'s environment_mode_selection_gate),
 // so s.environment_mode_selected is real once that stage has run; falls
 // back to the flat legend below (no tile highlighted) until it has.
 let modes = s.environment_mode_policy||{};
 let modeKeys = Object.keys(modes);
 let selectedMode = s.environment_mode_selected;
 document.getElementById('envmodetiles').innerHTML = modeKeys.length
   ? modeKeys.map(m=>
       `<div class="tile modeTile ${m===selectedMode?'mode-selected':''}"><div class="n">${m===selectedMode?'&#9654; ':''}${m}</div><div class="l">${modes[m].goal||''}</div></div>`
     ).join('')
   : tile('-','No environment_mode_policy.json found');

 // Subsystem Registry: real runtime registry, honest empty state.
 let subRows = (s.subsystem_registry||[]).map(sub=>
   `<tr style="border-bottom:1px solid #edf1f5"><td style="padding:4px">${sub.name||'-'}</td>`+
   `<td style="padding:4px">${sub.version||sub.release_sha||sub.git_sha||'-'}</td>`+
   `<td style="padding:4px">${sub.qualification_status||sub.qualification_state||'-'}</td></tr>`
 ).join('');
 document.getElementById('subsystemTableBody').innerHTML = subRows || '<tr><td style="padding:4px" colspan="3">No subsystems registered yet.</td></tr>';

 // Iron Rules / Qualification Tiers: the tier ladder tiles are classed
 // against qualification_tier_reached (real, from
 // _qualification_tier_reached() -- the highest tier any protocol in this
 // run's live protocol_capability_registry.json has actually reached), not
 // a flat unstyled tile -- tier-reached for tiers at/below that level,
 // tier-unreached above it (every tier renders tier-unreached when no
 // protocol is registered yet).
 let tierList = s.qualification_tiers||[];
 let reachedIdx = s.qualification_tier_reached ? tierList.indexOf(s.qualification_tier_reached) : -1;
 document.getElementById('ironrulestiles').innerHTML =
   tile(s.iron_rules_count!=null? s.iron_rules_count : '-','Iron Rules Enforced') +
   tierList.map((t,i)=>
     `<div class="tile tier ${i<=reachedIdx?'tier-reached':'tier-unreached'}"><div class="n">${i===reachedIdx?'&#9733;':(i<reachedIdx?'&#10003;':'')}</div><div class="l">${t}</div></div>`
   ).join('');
 document.getElementById('qualtierlegend').textContent = tierList.join(' -> ');

 let g=await (await fetch('/api/graph')).json();
 fillStageSelects((g.nodes||[]).map(n=>n.id));
 let h='';
 // Graph-level parallel fan-out/join: during a live fan-out, active_stages
 // names every concurrently-running branch, not just the parked source node
 // current_stage stays on -- highlight all of them (falls back to
 // [current_stage] via the same effective_active_stages() logic engine.py
 // itself uses, when active_stages is empty / no fan-out is in flight).
 let activeIds = (s.active_stages && s.active_stages.length) ? s.active_stages : [s.current_stage];
 (g.nodes||[]).forEach(n=>{
   let here = activeIds.includes(n.id);
   h+=`<div class="node ${here?'here':''}" style="cursor:pointer" onclick="showExplain('${n.id}')">${icon(n.status)}<div>${here?'&#9654; ':''}${n.id}</div>`+
      `<div class="${n.status}">${n.status}${n.agent?(' &middot; '+n.agent):''}</div></div>`;
 });
 document.getElementById('graph').innerHTML=h;

 await loadJobs();
 await loadAudit();
 await loadGuiAuditLog();
 await loadHumanGateCenter();
 await loadCoverageAnalysis();
 await loadAmbaFabric();
 await loadAmbaConnectivityMatrix();
 await loadAmbaPathExplorer();
 await loadAmbaBottleneck();
 await loadAmbaPerf();
 await loadAmbaPerfTrend();
 await loadResourceOrchestrator();
 await loadResearch();
 await loadConfidenceCalibration();
 await loadCrossProjectMining();
 await loadVerificationStrategy();
 await loadGenerationReadiness();
 await loadSelfLearningReadiness();
 await loadSmokeProof();
 await loadDesignKnowledge();
 await loadRequirementVplan();
 await loadQuestionQueue();
 await loadEvidenceIntegritySignoffBlockers();
 await loadTestSuiteCenter();
 await loadSubsystemSystemVerification();
 await loadVerificationArchitecture();
 await loadSystemTransactionE2EScoreboard();
 await loadVipEnvironmentBuilder();
 await loadOrphanedForkDetection();
 await loadMultiVipCooperation();
 await loadDutErrataCorrelation();
 await loadLoopCenter();
 await loadAgentActivity();
 await loadChangeImpact();
 await loadRegressionTier();
 await loadDependencySupplyChain();
 await loadScenarioPatternCorrespondence();
 await loadIntakeEvents();
 await loadPatternRuntimeState();
 await loadProtocolSelector();
 await loadIntakeBaseline();
 await loadBuildRemoteLsfIntake();
 await loadMemoryQualityPolicy();
 await loadNotificationCenter();
 await loadObservability();
 await showExplain(activeIds);
}
async function showExplain(stage){
 // Accepts a single stage id (click-through from a graph node) or an array
 // of stage ids (page load, all currently-active branches during a
 // fan-out) -- shown one after another, ALL branches rather than just the
 // first, so a live parallel fan-out is never silently reduced to one.
 let stages = Array.isArray(stage) ? stage : [stage];
 stages = stages.filter(Boolean);
 if(!stages.length) return;
 let blocks = await Promise.all(stages.map(async st=>{
   let e=await (await fetch('/api/de-explain?stage='+encodeURIComponent(st))).json();
   return '['+e.stage+']\\n'+e.explainer;
 }));
 document.getElementById('deexplain').textContent = blocks.join('\\n\\n');
}
load(); setInterval(load,3000); loadSessions(); loadUserInfo(); loadMemoryCenter();
initGlobalStatusBarSSE();  // P2-3: additive push-driven refresh on top of the poll loop above
</script></body></html>"""


def _lsf_summary(jobs):
    counts = {}
    pass_confirmed = fail_confirmed = early_kill = 0
    for j in jobs:
        lsf = j.get("lsf_status") or "UNKNOWN"
        counts[lsf] = counts.get(lsf, 0) + 1
        dv = j.get("dv_analysis_status") or j.get("sim_status") or ""
        if dv == "PASS":
            pass_confirmed += 1
        elif dv in ("FAIL", "ROOT_CAUSE", "RERUN_REQUIRED"):
            fail_confirmed += 1
        if j.get("early_kill"):
            early_kill += 1
    counts["total"] = len(jobs)
    counts["pass_confirmed"] = pass_confirmed
    counts["fail_confirmed"] = fail_confirmed
    counts["early_kill"] = early_kill
    counts["first_failure"] = _first_failure(jobs)
    return counts


def _first_failure(jobs):
    """Earliest job (by last_change_time) showing a real failure signal --
    EXIT status, early_kill, or a nonzero UVM_FATAL count -- not a fabricated
    number, derived from the same per-job JSON files LSF regression writes."""
    candidates = [
        j for j in jobs
        if j.get("lsf_status") == "EXIT" or j.get("early_kill")
        or (isinstance(j.get("uvm_fatal_count"), int) and j.get("uvm_fatal_count", 0) > 0)
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda j: j.get("last_change_time") or "")
    first = candidates[0]
    return {"job_id": first.get("job_id"), "timestamp": first.get("last_change_time")}


def _tail_events(root: Path, limit: int):
    """Last `limit` parsed lines of .dv-harness/events.jsonl, oldest first --
    the same append-only (open('a')) file h.store.event() writes one JSON
    object per line to; no os.replace() race here (unlike state.json/
    control.json), so a plain read_text() is safe. A line that fails to
    parse (e.g. a torn write caught mid-append) is skipped, not fatal."""
    events_file = root / ".dv-harness" / "events.jsonl"
    if not events_file.exists():
        return []
    try:
        raw = events_file.read_text(encoding="utf-8")
    except Exception:
        return []
    lines = [l for l in raw.strip().splitlines() if l.strip()]
    out = []
    for l in lines[-max(limit, 0):] if limit else []:
        try:
            out.append(json.loads(l))
        except Exception:
            continue
    return out


def _audit_trail(root: Path, limit: int = 50) -> Dict[str, Any]:
    """Answers 'who changed what, when' without opening files by hand:
    the last `limit` events.jsonl entries (every CLI/dashboard control-plane
    command already logs one via h.store.event(), see commands.py) plus the
    CURRENT control.json corrections/approvals/approval_history/cosigns --
    reused as-is by both GET /api/audit and CLI `dv-harness audit`."""
    root = Path(root)
    cp = ControlPlane(root).load()
    return {
        "limit": limit,
        "events": _tail_events(root, limit),
        "corrections": cp.get("corrections", {}),
        "approvals": cp.get("approvals", {}),
        "approval_history": cp.get("approval_history", {}),
        "cosigns": cp.get("cosigns", {}),
        # Structured GUI Audit Log (dv_harness/gui_audit_log.py): the same
        # events.jsonl entries above, filtered to the subset carrying the 7
        # named who/when/before/after/evidence/approval/result fields --
        # never a second store, just a richer per-record shape than the
        # generic `events` list already surfaces.
        "gui_audit_log": gui_audit_log.read_gui_audit_log(root, limit=limit),
    }


# --- GUI Action Audit Log (GET /api/gui-audit-log) --------------------------
# Dedicated rendered view for gui_audit_log.py's own structured 7-field
# records (who/when/before/after/evidence/approval/result), so a reviewer
# does not have to pick them out of the generic Audit Trail card's raw
# events.jsonl JSON blob above. Computes nothing itself: read_gui_audit_log()
# already filters the SAME events.jsonl _audit_trail() reads down to the
# type == GUI_AUDIT_RECORD_TYPE subset -- this endpoint only exposes that
# real reader as its own route/card, matching every other read-only card's
# "render, never re-derive" contract on this page.
def _read_gui_audit_log_state(root: Path, limit: int = 50, action: Optional[str] = None) -> Dict[str, Any]:
    """gui_audit_log.py's own real structured GUI action audit records for
    GET /api/gui-audit-log. `limit`/`action` mirror
    gui_audit_log.read_gui_audit_log()'s own keyword args and the CLI's
    `dv-harness gui-audit-log show --limit --action` verb exactly."""
    root = Path(root)
    records = gui_audit_log.read_gui_audit_log(root, limit=limit, action=action)
    return {
        "limit": limit,
        "action": action,
        "count": len(records),
        "records": records,
    }


# --- Human Gate Center (GET /api/human-gate-center) -------------------------
# GUI card centralizing gui_action_safety.py's real 11 consequential-action
# categories (21 declared actions) into one place a human reviews scope/
# impact/rollback BEFORE approving -- reusing that module's own already-real
# declarations verbatim, never a second classification of what a dashboard
# action means. This card computes no new judgment of its own: category,
# scope, impact, required_role, reversible and rollback_plan_kind are all
# gui_action_safety.GUI_ACTION_DECLARATIONS's own fields, read straight
# through, the same "render, never re-derive" contract every other read-only
# card on this page already holds to (_read_generation_readiness_state(),
# _read_smoke_proof_state(), ...).
#
# "Pending" is scoped deliberately narrowly, per real evidence rather than a
# guess: ControlPlane.get_approval(stage) is genuinely consulted by the
# engine only for the fixed commands.APPROVAL_ONLY_STAGES keys
# (RESEARCH_CAPABILITY_EVOLUTION / CHANGE_BLAST_RADIUS / BOUNDED_SELF_HEALING
# -- confirmed by grep before writing this: engine.py/gates.py/policy.py
# never read ControlPlane.get_approval() for an ordinary graph stage), plus
# the project's own real CURRENT stage (state.json's current_stage), which is
# the one other stage a human is realistically about to approve next.
# Rendering every graph stage's approval status here would misrepresent
# ordinary bookkeeping noise as a pending human gate.
def _read_human_gate_center_state(root: Path) -> Dict[str, Any]:
    """gui_action_safety.py's real 21-action declaration table plus real,
    already-recorded ControlPlane approval status for the governance stage
    keys the engine actually consults -- for GET /api/human-gate-center.
    Never approves, revokes, or mutates anything: this endpoint only reads
    the same control.json ControlPlane.approve() already writes, exactly the
    contract _audit_trail() above already holds to for the identical file."""
    root = Path(root)
    from . import gui_action_safety as gas
    from . import commands as _commands

    declarations = [
        {
            "action_id": d.action_id,
            "category": d.category,
            "scope": d.scope,
            "impact": d.impact,
            "required_role": d.required_role,
            "reversible": d.reversible,
            "rollback_plan_kind": d.rollback_plan_kind,
            "note": d.note,
        }
        for d in (gas.GUI_ACTION_DECLARATIONS[a] for a in gas.declared_actions())
    ]

    cp = ControlPlane(root).load()
    approvals = cp.get("approvals", {})
    approval_history = cp.get("approval_history", {})

    state = _read_json_file(root / ".dv-harness" / "state.json") or {}
    current_stage = state.get("current_stage")

    stage_keys: List[str] = []
    if current_stage:
        stage_keys.append(current_stage)
    for s in sorted(_commands.APPROVAL_ONLY_STAGES):
        if s not in stage_keys:
            stage_keys.append(s)

    governance_stages = []
    for stage in stage_keys:
        approval = approvals.get(stage)
        governance_stages.append({
            "stage": stage,
            "is_current_stage": stage == current_stage,
            "approved": approval is not None,
            "approval": approval,
            "history_count": len(approval_history.get(stage, [])),
        })

    return {
        "categories": list(gas.ACTION_CATEGORIES),
        "declarations": declarations,
        "governance_stages": governance_stages,
        # so the GUI can widen its own pre-existing Approve <select> to
        # include these fixed keys -- they are real, already-legal
        # commands.cmd_approve() arguments today (commands.py's own
        # _check_approval_stage()), just never populated into that select's
        # options, since fillStageSelects() only ever fills it from real
        # graph node ids.
        "approval_only_stages": sorted(_commands.APPROVAL_ONLY_STAGES),
    }


def _overall_progress(state: dict) -> int:
    """Percent of the canonical stages (len(Stage), NOT len(state['stages'])
    -- an on-disk state.json can predate later Stage enum additions and would
    silently understate the true denominator) that have reached PASS/CLOSED.

    The count itself is `loop_telemetry.gate_verified_stage_count()`, which is
    also what the Loop Engineering Center's Verified Gain column reports
    (LOOP-4, 2026-09-05). Delegating rather than keeping a second copy of the
    predicate is what stops the progress bar at the top of this page and that
    card's gain figure from ever disagreeing about which stages count."""
    from .loop_telemetry import gate_verified_stage_count
    done, total = gate_verified_stage_count(state.get("stages") or {})
    return round(100 * done / total) if total else 0


def _coverage_credit(root: Path):
    """Mirrors _execution_mode(): reads COVERAGE_CLOSURE's own recorded
    response for the coverage_signoff_verdict_gate evidence block's
    coverage_credit_percent, rather than inventing a number -- returns None
    (rendered as '-') until that stage has actually run and reported it."""
    state_file = root / ".dv-harness" / "state.json"
    state = _read_json_file(state_file)
    if state is None:
        return None
    stage_rec = (state.get("stages") or {}).get("COVERAGE_CLOSURE") or {}
    blocks = extract_evidence_blocks(stage_rec.get("last_message") or "")
    payload = blocks.get("coverage_signoff_verdict_gate")
    return payload.get("coverage_credit_percent") if payload else None


def _failure_attribution(root: Path):
    """Same _coverage_credit() pattern, for FAILURE_RECOVERY's
    `failure_attribution` evidence block: answers "was this a DUT (RTL) bug
    or a testbench bug" (the DE-facing gap USER_MANUAL.md section 10.10 used
    to document as a manual-JSON-reading exercise -- this closes it).

    Deliberately does NOT trust the agent's own `classification` field in
    the evidence block: tools/senior_dv/failure_attribution.py's gate never
    reads or cross-checks that field either -- it recomputes DUT_BUG/TB_BUG/
    UNKNOWN purely from `boundary_trace` (find the first entry where
    expected != observed; SEQUENCE/DRIVER/MONITOR/CHECKER/SCOREBOARD ->
    TB_BUG, DUT_INTERNAL/INTERFACE_OUT -> DUT_BUG, otherwise UNKNOWN) and
    that recomputed verdict is what gates PASS/FAIL on. An agent-stated
    `classification` that disagrees with its own boundary_trace would
    otherwise be silently trusted here -- this re-derives it identically to
    the gate script instead, so what the GUI shows can never be more
    trusting than what actually got the stage to PASS."""
    state_file = root / ".dv-harness" / "state.json"
    state = _read_json_file(state_file)
    if state is None:
        return None
    stage_rec = (state.get("stages") or {}).get("FAILURE_RECOVERY") or {}
    blocks = extract_evidence_blocks(stage_rec.get("last_message") or "")
    payload = blocks.get("failure_attribution")
    if not payload:
        return None
    first = None
    for s in payload.get("boundary_trace", []) or []:
        if s.get("expected") != s.get("observed"):
            first = s
            break
    verdict = "UNKNOWN"
    if first:
        st = first.get("stage")
        if st in ("SEQUENCE", "DRIVER", "MONITOR", "CHECKER", "SCOREBOARD"):
            verdict = "TB_BUG"
        elif st in ("DUT_INTERNAL", "INTERFACE_OUT"):
            verdict = "DUT_BUG"
    return {"verdict": verdict, "first_bad_event": first}


def _qualified_conclusion(root: Path):
    """Reads the real "qualified_conclusion" Blackboard topic
    (dv_harness/qualified_conclusion.py's QualifiedConclusion, written by
    engine.py's _score_root_cause_confidence -- see that module's own
    docstring) directly off disk, the same way _blackboard_topics() above
    lists topic files, rather than re-deriving anything: the composition
    (gate verdict + independently-recomputed confidence -> is_qualified)
    already happened in the engine, this just surfaces the persisted
    record. Returns None until RE_AUDIT has actually produced one (honest
    "not yet available" rather than a fabricated placeholder)."""
    payload = _read_json_file(root / ".dv-harness" / "blackboard" / "qualified_conclusion.json")
    if not isinstance(payload, dict):
        return None
    return payload.get("value")


def _execution_mode(root: Path):
    """Reads the ENV_CHECK stage's own recorded response and extracts the
    execution_mode_validator evidence block the agent supplied (the same
    gate wired in gates.py) -- not a separately-tracked state field, so this
    reflects exactly what was actually declared, or None if ENV_CHECK hasn't
    run/supplied that evidence yet."""
    state_file = root / ".dv-harness" / "state.json"
    state = _read_json_file(state_file)
    if state is None:
        return None
    env_check = (state.get("stages") or {}).get("ENV_CHECK") or {}
    blocks = extract_evidence_blocks(env_check.get("last_message") or "")
    payload = blocks.get("execution_mode_validator")
    return payload.get("execution_mode") if payload else None


def _environment_mode_selected(root: Path):
    """Intended per-run counterpart to _environment_mode_policy()'s static
    policy reference: scans every stage's own recorded last_message (same
    scan-all-stages shape _dv_review_pending() already uses) for a
    dv-harness-evidence environment_mode_selection block and returns its
    declared environment_mode field (SUBSYSTEM_MODE/SYSTEM_LEVEL_MODE,
    CLAUDE.md's Environment Generation Mode gate) -- or None otherwise.

    UPDATE (2026-09-01, route-skill-resolver-dynamic-implementation task):
    the gap this docstring used to document ("no stage anywhere in this
    engine currently EMITS an environment_mode_selection block") is closed.
    PROJECT_MODEL now mandates it (gates.STAGE_GATES["PROJECT_MODEL"]'s
    "environment_mode_selection" entry, tools/verification_flow/
    environment_mode_selection_gate.py), prompts.py's PROJECT_MODEL
    instructions tell the agent to produce it (echoing the real per-run
    decision dv_harness/environment_mode_router.py's resolve_environment_
    mode() already computed and folded into that stage's prompt via
    engine.py's route_info), and engine.py's normal evidence-block
    extraction is the writer -- no separate engine writer was needed since
    this scan already reads stage last_message text directly. This function
    itself required no code change to start working once a real producer
    existed, exactly as anticipated below."""
    state_file = root / ".dv-harness" / "state.json"
    state = _read_json_file(state_file)
    if state is None:
        return None
    for stage_rec in (state.get("stages") or {}).values():
        blocks = extract_evidence_blocks(stage_rec.get("last_message") or "")
        payload = blocks.get("environment_mode_selection")
        if payload:
            return payload.get("environment_mode")
    return None


def _dv_review_pending(root: Path):
    """Mirrors _coverage_credit()/_execution_mode(): scans every stage's own
    recorded last_message for dv-harness-evidence blocks and reports, by
    stage/gate_id/field, exactly which DV_JUDGMENT-tagged (gates.py
    JUDGMENT_FIELDS) fields still lack a valid {"value","reviewer_id",
    "reviewer_confidence"} co-sign -- the same Tier 5 rule gates.py's
    _check_judgment_fields() enforces at stage-promotion time (when
    policy.require_dv_review_cosign is enabled), so a solo DE gets a live,
    itemized handoff list instead of "have a DV engineer review everything".
    This reporting is always shown regardless of whether enforcement is
    enabled -- it's an informational preview, not a gate. A field tagged
    classification_basis:"REUSED_CCL:<id>" (gates.CCL_SKIPPABLE) is excluded
    here too, same as at promotion time."""
    state_file = root / ".dv-harness" / "state.json"
    state = _read_json_file(state_file)
    if state is None:
        return {"count": 0, "fields": []}
    pending = []
    for stage_id, srec in (state.get("stages") or {}).items():
        blocks = extract_evidence_blocks(srec.get("last_message") or "")
        for gate_id, payload in blocks.items():
            specs = JUDGMENT_FIELDS.get(gate_id)
            if not specs or not isinstance(payload, dict):
                continue
            for path in specs:
                skippable = (gate_id, path) in CCL_SKIPPABLE
                for container, key, loc in _iter_judgment_targets(payload, path):
                    v = container.get(key)
                    if skippable:
                        basis = container.get("classification_basis")
                        if isinstance(basis, str) and basis.startswith("REUSED_CCL:"):
                            continue
                    ok = (isinstance(v, dict) and "value" in v
                          and bool(str(v.get("reviewer_id") or "").strip())
                          and v.get("reviewer_confidence") in REVIEWER_CONFIDENCE_LEVELS)
                    if not ok:
                        pending.append(f"{stage_id}/{gate_id}/{loc}")
    return {"count": len(pending), "fields": pending}


def _graph_with_status(root: Path, current_stage: str):
    graph_file = root / ".dv-harness" / "graph" / "main_graph.json"
    state_file = root / ".dv-harness" / "state.json"
    if not graph_file.exists():
        return {"nodes": []}
    graph = _read_json_file(graph_file, default={})
    stage_status = {}
    state = _read_json_file(state_file)
    if state is not None:
        for sid, srec in (state.get("stages") or {}).items():
            stage_status[sid] = srec.get("status", "NOT_STARTED")
    nodes = []
    for n in graph.get("nodes", []):
        nodes.append({
            "id": n["id"], "agent": n.get("agent"),
            "status": stage_status.get(n["id"], "N/A"),
        })
    return {"nodes": nodes}


def _protocol_registry(root: Path):
    """Reads the real qualification/protocol_capability_registry.json this
    project's protocol builders are actually tracked in (never a hardcoded
    protocol list) -- returns [] if the file is missing rather than
    fabricating protocols.

    Carries capability_status/protocol_model_generator alongside
    qualification_status (2026-09-04). A tile showing only qualification_status
    said BUILDER_AVAILABLE for all 11 protocols, which reads as "a builder
    exists, equally, for every one of these" -- true only of the
    protocol-agnostic skeleton. capability_status is the separate question of
    whether any protocol-SPECIFIC generation code exists, derived in
    protocol_capability.py from modules verified to import; see that module for
    why one field could not answer both."""
    path = root / ".dv-harness" / "qualification" / "protocol_capability_registry.json"
    data = _read_json_file(path, default=None)
    if not isinstance(data, dict):
        return []
    protocols = data.get("protocols") or {}
    out = []
    for name, rec in protocols.items():
        if not isinstance(rec, dict):
            continue
        out.append({
            "name": name,
            "qualification_status": rec.get("qualification_status") or rec.get("status") or "-",
            "capability_status": rec.get("capability_status") or "-",
            "protocol_model_generator": rec.get("protocol_model_generator") or "NONE",
        })
    out.sort(key=lambda p: p["name"])
    return out


def _environment_mode_policy(root: Path):
    """Reads the real environment-router/environment_mode_policy.json --
    the two canonical modes (SUBSYSTEM_MODE/SYSTEM_LEVEL_MODE) CLAUDE.md's
    Environment Generation Mode gate defines. This is deliberately just the
    static policy reference; see _environment_mode_selected() below for
    which mode (if any) the CURRENT run actually declared via a real
    environment_mode_selection evidence block (PROJECT_MODEL now mandates
    one -- see that function's own docstring)."""
    path = root / ".dv-harness" / "environment-router" / "environment_mode_policy.json"
    data = _read_json_file(path, default=None)
    if not isinstance(data, dict):
        return None
    modes = data.get("modes") or {}
    return {name: {"goal": rec.get("goal")} for name, rec in modes.items() if isinstance(rec, dict)}


def _subsystem_registry(root: Path):
    """Reads the REAL runtime registry engine.py's own
    _persist_subsystem_registry_entry() writes to
    (soc-composer/subsystem_environment_registry.json) -- distinct from the
    empty subsystem_environment_registry_template.json example next to it.
    Returns [] (rendered as an honest empty state) when no subsystem has
    ever been registered yet in this project."""
    path = root / ".dv-harness" / "soc-composer" / "subsystem_environment_registry.json"
    data = _read_json_file(path, default=None)
    if not isinstance(data, dict):
        return []
    return [s for s in (data.get("subsystems") or []) if isinstance(s, dict)]


def _iron_rules_count(root: Path) -> int:
    from .stats_snapshot import _iron_rule_count
    return _iron_rule_count(root)


def _qualification_tiers():
    """Static reference legend (the ladder itself): dv_harness.qualification.
    QualificationTier's own 8-tier vocabulary, in enum declaration order.
    See _qualification_tier_reached() below for which tier this run has
    actually reached against that ladder."""
    from .qualification import QualificationTier
    return [t.value for t in QualificationTier]


def _qualification_tier_reached(root: Path):
    """Real per-run counterpart to _qualification_tiers()'s static ladder:
    the highest CANONICAL_LADDER tier actually reached by any protocol in
    this project's live protocol_capability_registry.json (_protocol_registry()
    above) -- None if no protocol is registered yet, or none of the
    registered qualification_status values is one of the 8 canonical tokens
    (e.g. still a legacy/non-canonical vocabulary value)."""
    from .qualification import CANONICAL_LADDER
    protocols = _protocol_registry(root)
    reached_ranks = [CANONICAL_LADDER.index(p["qualification_status"]) for p in protocols
                     if p.get("qualification_status") in CANONICAL_LADDER]
    if not reached_ranks:
        return None
    return CANONICAL_LADDER[max(reached_ranks)]


# --- Coverage analysis (.dv-harness/coverage/summary.json + history.json) --
# Poster-compliance audit (2026-08-29): coverage_analysis.py's parse/holes/
# trend logic was real but had zero callers in dv_harness/ (only the
# standalone tools/analyze_coverage.py CLI script used it) -- GET
# /api/coverage below is the actual wiring, following the same
# read-real-file-honest-empty-state pattern as _coverage_credit()/
# _protocol_registry() elsewhere in this module.
def _coverage_dir(root: Path) -> Path:
    return root / ".dv-harness" / "coverage"


def _default_coverage_summary_path(root: Path) -> Path:
    return _coverage_dir(root) / "summary.json"


def _default_coverage_history_path(root: Path) -> Path:
    return _coverage_dir(root) / "history.json"


def _read_coverage_state(root: Path, summary_path: Optional[Path] = None,
                          history_path: Optional[Path] = None) -> Dict[str, Any]:
    """Reads a real coverage-summary JSON (default
    .dv-harness/coverage/summary.json, overridable so a project can point at
    wherever its own coverage tool actually writes) and calls
    coverage_analysis.parse_coverage_summary()/identify_holes() over it, plus
    compute_coverage_trend()/render_coverage_trend_svg() over
    .dv-harness/coverage/history.json when it holds >= 2 samples. No summary
    file yet -> {"available": False, ...}, the honest pre-first-run state,
    never a fabricated 0%/100%. A malformed summary/history file reports the
    same CoverageAnalysisError reason/detail parse_coverage_summary() itself
    raises, rather than a generic 500 -- this is a read of possibly-external
    tool output, not a client request body."""
    from . import coverage_analysis as ca

    s_path = Path(summary_path) if summary_path else _default_coverage_summary_path(root)
    h_path = Path(history_path) if history_path else _default_coverage_history_path(root)

    if not s_path.exists():
        return {"available": False, "summary_path": str(s_path), "history_path": str(h_path)}

    try:
        raw = json.loads(s_path.read_text(encoding="utf-8"))
    except Exception as e:
        return {"available": True, "summary_path": str(s_path), "history_path": str(h_path),
                "categories": None, "holes": None, "history": None, "trend": None, "trend_svg": None,
                "error": {"reason": "MALFORMED_JSON", "detail": {"message": str(e)}}}

    try:
        parsed = ca.parse_coverage_summary(raw)
    except ca.CoverageAnalysisError as e:
        return {"available": True, "summary_path": str(s_path), "history_path": str(h_path),
                "categories": None, "holes": None, "history": None, "trend": None, "trend_svg": None,
                "error": {"reason": e.reason, "detail": e.detail}}

    holes = ca.identify_holes(parsed)

    history = None
    if h_path.exists():
        try:
            loaded = json.loads(h_path.read_text(encoding="utf-8"))
            history = loaded if isinstance(loaded, list) else None
        except Exception:
            history = None

    trend = None
    trend_svg = None
    if isinstance(history, list) and len(history) >= 2:
        trend = ca.compute_coverage_trend(history)
        trend_svg = ca.render_coverage_trend_svg(history)

    return {
        "available": True,
        "summary_path": str(s_path),
        "history_path": str(h_path),
        "categories": parsed["categories"],
        "holes": holes,
        "history": history,
        "trend": trend,
        "trend_svg": trend_svg,
        "error": None,
    }


# --- AMBA fabric / VIP bind / scoreboard registry (GET /api/amba) ----------
# GUI-09 (2026-09-05 GUI completeness audit): dashboard.py contained zero
# references to the AMBA discovery pipeline, even though
# amba_fabric_discovery.py -> amba_port_registry.py -> amba_scoreboard_env.py
# already produce the one artifact that joins every fact a fabric reviewer
# needs -- AMBA-22's AMBA_PORT_REGISTRY, one row per discovered fabric port
# carrying protocol, fabric/endpoint role, the traced endpoint hierarchy, the
# AMBA-15 widths, the AMBA-20 vip_mode, and the AMBA-21 scoreboard_channel that
# port's proposed VIP monitor would feed.
#
# This reads that registry off disk through the REAL
# amba_port_registry.load_amba_port_registry() (which runs the module's own
# assert_registry_complete() on the way in, so a row with a silently-absent
# column is reported as an error rather than rendered as a blank cell) and
# derives the master/slave/unresolved split through the REAL
# registry_endpoints() -- never a second, dashboard-local re-derivation of
# either. Same read-real-file-honest-empty-state contract as
# _read_coverage_state() above: no registry on disk yet is {"available": False},
# never a fabricated port.
#
# DISCOVERY AND PLANNING ONLY (AMBA-30 / AMBA-31): every `vip_bind_hierarchy`
# this surfaces is a PROPOSED location a human reviews, not a bind statement.
# That is why this endpoint is GET-only and the card is read-only -- approving
# a fabric bind plan from a browser form would be exactly the auto-acceptance
# amba_port_registry.py's own module docstring refuses.
def _default_amba_registry_path(root: Path) -> Path:
    return root / ".dv-harness" / "amba" / "amba_port_registry.json"


def _read_amba_registry_state(root: Path,
                               registry_path: Optional[Path] = None) -> Dict[str, Any]:
    """Real AMBA_PORT_REGISTRY rows + the derived endpoint/readiness/scoreboard
    summary for GET /api/amba.

    `registry_path` is overridable (like _read_coverage_state()'s summary/history
    paths) so a project whose AMBA discovery pass wrote its registry elsewhere
    can point at it without this module guessing a second location.

    A registry that fails amba_port_registry.assert_registry_complete() reports
    that module's own PortRegistryError reason/detail rather than a generic 500:
    this is a read of an artifact another pipeline produced, not a client request
    body, and "which column is missing on which port_id" is exactly what the
    reviewer needs to see."""
    from . import amba_port_registry as apr
    from .amba_fabric_discovery import FabricDiscoveryError, parent_matrix_rows
    from .connectivity import REQUIRED_HUMAN_INPUT

    path = Path(registry_path) if registry_path else _default_amba_registry_path(root)
    empty = {"available": False, "registry_path": str(path), "rows": [],
             "endpoints": None, "summary": None, "error": None}
    if not path.exists():
        return empty

    try:
        rows = apr.load_amba_port_registry(path)
    except FabricDiscoveryError as e:
        return {**empty, "available": True,
                "error": {"reason": e.reason, "detail": e.detail}}
    except Exception as e:
        return {**empty, "available": True,
                "error": {"reason": "MALFORMED_REGISTRY_FILE", "detail": {"message": str(e)}}}

    endpoints = apr.registry_endpoints(rows)
    readiness_counts: Dict[str, int] = {}
    for r in rows:
        key = str(r.get("readiness") or "UNKNOWN")
        readiness_counts[key] = readiness_counts.get(key, 0) + 1
    vip_planned = sum(1 for r in rows if r.get("vip_mode") != apr.VIP_MODE_NOT_PLANNED)
    # A scoreboard_channel of REQUIRED_HUMAN_INPUT is amba_scoreboard_env's own
    # sentinel for "nothing established where this monitor would feed" -- counted
    # separately rather than folded in, because a blank cell reads as an
    # oversight and a mapped channel is a materially different review state.
    sb_mapped = sum(1 for r in rows
                    if r.get("scoreboard_channel") not in (None, "", REQUIRED_HUMAN_INPUT))
    return {
        "available": True,
        "registry_path": str(path),
        "rows": rows,
        "endpoints": endpoints,
        "summary": {
            # parent_matrix_rows(): counting the raw row list would count a
            # multiple-destination port once per traced branch.
            "fabric_port_count": len(parent_matrix_rows(rows)),
            "row_count": len(rows),
            "readiness_counts": readiness_counts,
            "vip_planned": vip_planned,
            "vip_not_planned": len(rows) - vip_planned,
            "scoreboard_channel_mapped": sb_mapped,
            "scoreboard_channel_required_human_input": len(rows) - sb_mapped,
            "traced_master_count": len(endpoints["masters"]),
            "traced_slave_count": len(endpoints["slaves"]),
            "unresolved_count": len(endpoints["unresolved"]),
        },
        "error": None,
    }


# --- AMBA Fabric Connectivity Matrix (GET /api/amba-connectivity-matrix) ---
# dashboard_amba_connectivity_matrix_ui: dashboard.py had no card rendering
# amba_fabric_graph_ir.py's real node/edge topology -- that module builds a
# real AMBAFabricGraphIR from caller-declared nodes/edges (the twelve-kind
# internal-fabric-component vocabulary plus master/slave endpoints, every
# node/edge requiring a real evidence citation, and a reconfigurable/dynamic
# claim requiring grounded evidence per
# assert_no_ungrounded_reconfigurable_claim()) but had no dashboard surface at
# all.
#
# This reads a project's own declared fabric graph off disk -- the same
# `.dv-harness/amba/` convention _default_amba_registry_path() above already
# uses -- and runs it straight through
# amba_fabric_graph_ir.build_amba_fabric_graph(): never a second,
# dashboard-local re-derivation of node-kind legality, evidence-citation
# requirements, or reconfigurable-claim grounding. A project with no declared
# graph yet reports the honest empty state below, never a fabricated node or
# edge; a graph that module refuses to build reports its real
# AMBAFabricGraphError code/detail instead of a generic 500.
#
# Read-only by design, same as the AMBA-22 registry card above: this module
# builds an IR a human reads -- nothing here writes a bind statement or a
# topology decision.
def _default_amba_fabric_graph_path(root: Path) -> Path:
    return root / ".dv-harness" / "amba" / "amba_fabric_graph.json"


def _read_amba_fabric_graph_state(root: Path,
                                   graph_path: Optional[Path] = None) -> Dict[str, Any]:
    """Real AMBAFabricGraphIR node/edge rows for GET /api/amba-connectivity-matrix.

    The on-disk document is `{"nodes": [...], "edges": [...]}` -- the same two
    lists `amba_fabric_graph_ir.build_amba_fabric_graph(nodes, edges)` already
    takes. This function is a thin JSON-file front door onto that real
    builder, never a second graph model: every node/edge field returned below
    is read straight off the real `FabricNodeIR`/`FabricEdgeIR` objects that
    builder produces.

    `graph_path` is overridable (like _read_amba_registry_state()'s
    `registry_path`) so a project whose fabric-topology declaration lives
    elsewhere can point at it without this module guessing a second location.
    """
    from .amba_fabric_graph_ir import AMBAFabricGraphError, build_amba_fabric_graph

    path = Path(graph_path) if graph_path else _default_amba_fabric_graph_path(root)
    empty = {"available": False, "graph_path": str(path), "nodes": [], "edges": [],
             "summary": None, "error": None}
    if not path.exists():
        return empty

    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return {**empty, "available": True,
                "error": {"reason": "MALFORMED_GRAPH_FILE", "detail": {"message": str(e)}}}

    try:
        graph = build_amba_fabric_graph(doc.get("nodes") or [], doc.get("edges") or [])
    except AMBAFabricGraphError as e:
        return {**empty, "available": True,
                "error": {"reason": e.code, "detail": e.detail}}
    except Exception as e:
        return {**empty, "available": True,
                "error": {"reason": "GRAPH_BUILD_FAILED", "detail": {"message": str(e)}}}

    node_rows = [{"node_id": n.node_id, "kind": n.kind,
                  "reconfigurable": bool(n.attributes.get("reconfigurable") or
                                          n.attributes.get("dynamic")),
                  "evidence": "; ".join(str(ev.get("citation") or ev) for ev in n.evidence)}
                 for n in graph.nodes]
    edge_rows = [{"edge_id": e.edge_id, "from": e.from_node, "to": e.to_node,
                  "evidence": "; ".join(str(ev.get("citation") or ev) for ev in e.evidence)}
                 for e in graph.edges]

    return {
        "available": True,
        "graph_path": str(path),
        "nodes": node_rows,
        "edges": edge_rows,
        "summary": {
            "node_count": len(node_rows),
            "edge_count": len(edge_rows),
            "reconfigurable_node_count": sum(1 for n in node_rows if n["reconfigurable"]),
        },
        "error": None,
    }


# --- AMBA Path Explorer (GET /api/amba-path-explorer) -----------------------
# dashboard_amba_path_explorer_ui: amba_fabric_graph_ir.py's own AMBAPathIR
# (build_amba_path_ir()) already enumerates every real, caller-declared route
# for a (master, slave) pair -- preserving every distinct declared route
# rather than collapsing them, and cross-checking each route's own hop
# sequence against the real fabric graph's edges when both are supplied
# (ROUTE_CONSISTENT_WITH_GRAPH / ROUTE_INCONSISTENT_WITH_GRAPH /
# ROUTE_CONSISTENCY_NOT_CHECKED) -- but had no dashboard surface letting a
# human pick one (master, slave) pair and see its real declared route(s).
#
# Route facts are read from the SAME on-disk document
# _read_amba_fabric_graph_state() already reads
# (.dv-harness/amba/amba_fabric_graph.json), widened with an optional
# "routes" list carrying build_amba_path_ir()'s own RouteFact shape
# (master_id/slave_id/hops/evidence/route_id) -- one artifact for this
# module's whole IR, never a second file to keep in sync with the first.
# This is read-only and re-derives nothing: every route/consistency finding
# below is build_amba_path_ir()'s own real output, run against the SAME
# build_amba_fabric_graph() the connectivity-matrix card above already calls,
# so the two cards can never disagree about what the graph itself contains.
def _read_amba_path_explorer_state(root: Path, master: Optional[str] = None,
                                    slave: Optional[str] = None,
                                    graph_path: Optional[Path] = None) -> Dict[str, Any]:
    """Real AMBAPathIR route rows for a caller-picked (master, slave) pair,
    for GET /api/amba-path-explorer.

    `master`/`slave` select one declared pair to show routes for; omitted,
    every declared pair is still listed (for the picker), with `paths` left
    empty. A pair nobody declared a route for reports zero paths rather than
    an error or a fabricated one -- AMBAPathIR.paths_for() already returns
    () for such a pair, and this function trusts that empty result exactly
    as-is rather than treating "no declared route" as a failure.
    """
    from .amba_fabric_graph_ir import (
        AMBAFabricGraphError, build_amba_fabric_graph, build_amba_path_ir)

    path = Path(graph_path) if graph_path else _default_amba_fabric_graph_path(root)
    empty = {"available": False, "graph_path": str(path), "pairs": [],
             "master": master or None, "slave": slave or None, "paths": [], "error": None}
    if not path.exists():
        return empty

    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return {**empty, "available": True,
                "error": {"reason": "MALFORMED_GRAPH_FILE", "detail": {"message": str(e)}}}

    nodes = doc.get("nodes") or []
    edges = doc.get("edges") or []
    routes = doc.get("routes") or []

    # A graph is optional for path enumeration (build_amba_path_ir() accepts
    # graph=None -- every route then honestly reports CONSISTENCY_NOT_CHECKED
    # rather than a fabricated CONSISTENT_WITH_GRAPH) but, when nodes/edges
    # ARE declared, it is built through the real validator so a broken graph
    # is reported here exactly as the connectivity-matrix card reports it.
    graph = None
    if nodes or edges:
        try:
            graph = build_amba_fabric_graph(nodes, edges)
        except AMBAFabricGraphError as e:
            return {**empty, "available": True,
                    "error": {"reason": e.code, "detail": e.detail}}
        except Exception as e:
            return {**empty, "available": True,
                    "error": {"reason": "GRAPH_BUILD_FAILED", "detail": {"message": str(e)}}}

    try:
        path_ir = build_amba_path_ir(routes, graph=graph)
    except AMBAFabricGraphError as e:
        return {**empty, "available": True,
                "error": {"reason": e.code, "detail": e.detail}}
    except Exception as e:
        return {**empty, "available": True,
                "error": {"reason": "PATH_IR_BUILD_FAILED", "detail": {"message": str(e)}}}

    pairs = [{"master": m, "slave": s} for (m, s) in path_ir.pairs()]

    selected_paths = []
    if master and slave:
        for p in path_ir.paths_for(master, slave):
            selected_paths.append({
                "route_id": p.route_id, "master": p.master_id, "slave": p.slave_id,
                "hops": list(p.hops),
                "evidence": [str(ev.get("citation") or ev) for ev in p.evidence],
                "consistency": p.consistency_status,
                "findings": list(p.consistency_findings),
            })

    return {
        "available": True,
        "graph_path": str(path),
        "pairs": pairs,
        "master": master or None,
        "slave": slave or None,
        "paths": selected_paths,
        "error": None,
    }


# --- AMBA Bottleneck Analysis (GET /api/amba-bottleneck) --------------------
# dashboard_amba_bottleneck_analysis_ui: amba_performance_classification.py's
# identify_bottleneck_candidate() already builds a structured
# Hypothesis -> Evidence -> Confidence -> Gap -> Next-Best-Action record --
# refusing to build one from fewer than MIN_BOTTLENECK_EVIDENCE_COUNT (2) real
# correlated evidence citations -- but had no dashboard surface at all.
#
# This reads a project's own declared bottleneck-candidate inputs off disk
# (the same `.dv-harness/amba/` convention _default_amba_registry_path() /
# _default_amba_fabric_graph_path() above already use) and runs each one
# straight through identify_bottleneck_candidate(): never a second,
# dashboard-local re-derivation of the confidence-from-evidence-count rule or
# the minimum-evidence refusal. A project with no declared candidates yet
# reports the honest empty state below, never a fabricated candidate; a
# declaration this module refuses to build (fewer than 2 real evidence
# citations, an empty hypothesis) reports its real
# PerformanceClassificationError message against that one candidate only --
# never a generic 500, and never silently dropped from the response.
#
# Read-only by design, same as the two AMBA cards above: this renders a
# candidate record a human reads -- nothing here decides a root cause, runs a
# build/simulation, or writes a verification verdict.
def _default_amba_bottleneck_candidates_path(root: Path) -> Path:
    return root / ".dv-harness" / "amba" / "bottleneck_candidates.json"


def _read_amba_bottleneck_state(root: Path,
                                 candidates_path: Optional[Path] = None) -> Dict[str, Any]:
    """Real BottleneckCandidateRecord rows for GET /api/amba-bottleneck.

    The on-disk document is `{"candidates": [{"id", "hypothesis", "evidence":
    [...], "gap"?, "next_best_action"?}, ...]}` -- each entry is exactly
    `identify_bottleneck_candidate()`'s own real parameters. This function is a
    thin JSON-file front door onto that real builder, never a second
    bottleneck-classification engine: every hypothesis/evidence/confidence/
    gap/next_best_action field returned below is read straight off the real
    `BottleneckCandidateRecord` that builder produces.
    """
    from .amba_performance_classification import (
        PerformanceClassificationError, identify_bottleneck_candidate)

    path = Path(candidates_path) if candidates_path else _default_amba_bottleneck_candidates_path(root)
    empty = {"available": False, "candidates_path": str(path), "candidates": [],
             "rejected": [], "error": None}
    if not path.exists():
        return empty

    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return {**empty, "available": True,
                "error": {"reason": "MALFORMED_CANDIDATES_FILE", "detail": {"message": str(e)}}}

    declared = doc.get("candidates") or []
    candidates: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    for idx, entry in enumerate(declared):
        if not isinstance(entry, dict):
            rejected.append({"id": None, "index": idx, "reason": "CANDIDATE_NOT_AN_OBJECT"})
            continue
        cand_id = entry.get("id") or f"candidate-{idx}"
        try:
            record = identify_bottleneck_candidate(
                entry.get("hypothesis"),
                entry.get("evidence") or [],
                gap=entry.get("gap"),
                next_best_action=entry.get("next_best_action"),
            )
        except PerformanceClassificationError as e:
            rejected.append({"id": cand_id, "index": idx, "reason": str(e)})
            continue
        except Exception as e:
            rejected.append({"id": cand_id, "index": idx, "reason": f"UNEXPECTED_ERROR: {e}"})
            continue
        candidates.append({
            "id": cand_id,
            "hypothesis": record.hypothesis,
            "evidence": list(record.evidence),
            "confidence": record.confidence,
            "gap": record.gap,
            "next_best_action": record.next_best_action,
        })

    return {
        "available": True,
        "candidates_path": str(path),
        "candidates": candidates,
        "rejected": rejected,
        "error": None,
    }


# --- Resource Orchestrator (GET /api/resource-orchestrator) -----------------
# resource-orchestrator-no-dashboard-card: resource_orchestrator.py (VI-5's
# global cross-job license/queue-slot arbitration, 53 tests) already has its
# own real `python -m dv_harness.resource_orchestrator` front door and its own
# real `dv-harness resource-orchestrator` CLI verb, but had zero real usage in
# dashboard.py -- an operator could not see the cross-job GRANTED/QUEUED/
# DEFERRED grant ranking anywhere in the GUI.
#
# This reads a project's own declared plan inputs off disk (a new
# `.dv-harness/resource_orchestrator/` convention, matching the `.dv-harness/
# amba/` convention the AMBA cards above already use) and runs them straight
# through resource_orchestrator.orchestrate(): never a second, dashboard-local
# arbitration engine, never a re-derivation of the real anti-monopoly/FIFO/
# tie-break ranking rules or the real GRANTED/QUEUED/DEFERRED decision.
#
# The declared document is `{"requests": [...], "checks": [...], "queue": "...",
# "live_jobs": [...], "cfg": {...}}`. "requests" entries are exactly
# ResourceRequest-shaped dicts (project_id/stage/consumes_scarce_resource/...) --
# resource_orchestrator._coerce_request() already accepts a plain dict, so no
# conversion happens here. "checks" entries are exactly preflight.CheckOutcome's
# own fields (name/status/detail/command/evidence); a check missing a real
# name/status is skipped rather than guessed. Omitting "requests" entirely
# (rather than declaring an empty list) means "build contenders from the real
# cross-project registry" -- resource_orchestrator.contenders_from_registry(),
# called for real, never re-implemented -- so a project that has never
# declared explicit requests still gets a real answer from its own registered
# projects, or an honest NO_CONTENDERS note when nothing is registered either.
#
# Read-only by design, same as the AMBA cards: this renders a REAL arbitration
# PLAN a human reads -- nothing here submits, kills, or reserves a job, and a
# GRANT authorizes nothing (resource_orchestrator.py's own PLAN_DISCLOSURE,
# carried through to this card verbatim below).
def _default_resource_orchestrator_inputs_path(root: Path) -> Path:
    return root / ".dv-harness" / "resource_orchestrator" / "plan_inputs.json"


def _read_resource_orchestrator_state(root: Path,
                                       inputs_path: Optional[Path] = None) -> Dict[str, Any]:
    """Real resource_orchestrator.ArbitrationPlan for GET /api/resource-orchestrator.

    A thin JSON-file front door onto the real orchestrate() front door -- every
    allocation/decision/rank/reason/capacity field returned below is read
    straight off the real ArbitrationPlan that function produces.
    """
    from . import resource_orchestrator as ro
    from .preflight import CheckOutcome

    path = Path(inputs_path) if inputs_path else _default_resource_orchestrator_inputs_path(root)
    empty = {"available": False, "inputs_path": str(path), "plan": None,
             "skipped": [], "note": None, "error": None}
    if not path.exists():
        return empty

    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return {**empty, "available": True,
                "error": {"reason": "MALFORMED_INPUTS_FILE", "detail": {"message": str(e)}}}

    if not isinstance(doc, dict):
        return {**empty, "available": True,
                "error": {"reason": "INPUTS_NOT_AN_OBJECT", "detail": {}}}

    checks: List[CheckOutcome] = []
    for c in (doc.get("checks") or []):
        if not isinstance(c, dict) or not c.get("name") or not c.get("status"):
            continue
        checks.append(CheckOutcome(
            name=str(c["name"]), status=str(c["status"]), detail=str(c.get("detail") or ""),
            command=c.get("command"), evidence=c.get("evidence"),
        ))

    queue = str(doc.get("queue") or "")
    live_jobs = doc.get("live_jobs")
    if not isinstance(live_jobs, list):
        live_jobs = None
    cfg = doc.get("cfg") if isinstance(doc.get("cfg"), dict) else None

    skipped: List[Dict[str, Any]] = []
    if "requests" in doc:
        declared_requests = doc.get("requests")
        if not isinstance(declared_requests, list):
            return {**empty, "available": True,
                    "error": {"reason": "REQUESTS_NOT_A_LIST", "detail": {}}}
        requests: List[Any] = declared_requests
    else:
        try:
            requests, skipped = ro.contenders_from_registry(root)
        except Exception as e:
            return {**empty, "available": True,
                    "error": {"reason": "CONTENDERS_FROM_REGISTRY_FAILED",
                              "detail": {"message": str(e)}}}

    if not requests:
        return {"available": True, "inputs_path": str(path), "plan": None,
                "skipped": skipped, "error": None,
                "note": "NO_CONTENDERS -- no resource requests were declared and no registered "
                        "project carries a readable current stage."}

    try:
        plan = ro.orchestrate(requests, checks=checks, cfg=cfg, queue=queue, live_jobs=live_jobs)
    except ro.ResourceOrchestratorError as e:
        return {**empty, "available": True,
                "error": {"reason": "MALFORMED_REQUEST", "detail": {"message": str(e)}}}
    except Exception as e:
        return {**empty, "available": True,
                "error": {"reason": "UNEXPECTED_ERROR", "detail": {"message": str(e)}}}

    return {"available": True, "inputs_path": str(path), "plan": plan.to_dict(),
            "skipped": skipped, "note": None, "error": None}


# --- AMBA Per-Port Performance Center (GET /api/amba-performance) -----------
# dashboard_amba_per_port_performance_center: amba_performance_calculator.py's
# real PortPerformanceIR/PathPerformanceIR aggregates -- pure arithmetic over
# real, caller-supplied samples, with an explicit COMPUTED/UNKNOWN/
# NOT_APPLICABLE status on every metric -- had no dashboard surface at all.
#
# This reads a project's own declared per-port/per-path samples off disk (the
# same `.dv-harness/amba/` convention the other AMBA cards above already use)
# and runs each declared entry straight through
# amba_performance_calculator.aggregate_port_performance(): never a second,
# dashboard-local performance-arithmetic engine. A path entry reuses the exact
# same real aggregation (bandwidth/throughput/latency percentiles are pure
# functions of the samples, independent of whether the id names a port or a
# source->dest path) and is then repackaged, unmodified, into a real
# `PathPerformanceIR` instance -- only the subset of fields that dataclass
# actually declares, never a fourth, invented arithmetic path.
#
# Every metric's own real `status` (COMPUTED/UNKNOWN/NOT_APPLICABLE) is
# rendered honestly: a port/path with no declared
# peak_bandwidth_bytes_per_second, no declared latency_definition, or an empty
# samples list reports the real UNKNOWN/NOT_APPLICABLE finding that module's
# own rules produce -- never a fabricated number. A declaration this module
# refuses to build (an invalid latency definition, a negative byte count)
# reports its real PerformanceCalculatorError message against that one entry
# only -- never a generic 500, and never silently dropped from the response.
#
# Read-only by design, same as the AMBA cards above: this renders a real
# arithmetic result a human reads -- nothing here decides a root cause, runs a
# build/simulation, or writes a verification verdict. This harness owns no
# live simulator; every number shown is caller-supplied evidence, never
# estimated.
def _default_amba_performance_samples_path(root: Path) -> Path:
    return root / ".dv-harness" / "amba" / "performance_samples.json"


_PERF_SAMPLE_FIELDS = (
    "sample_id", "start_time", "end_time", "byte_count", "transaction_count",
    "latency", "latency_definition", "outstanding_count", "busy_cycles",
    "stalled_cycles", "total_cycles", "source_evidence",
)


def _perf_samples_from_declared(declared: List[Any], id_prefix: str) -> List[Any]:
    """Builds real `PerformanceSampleIR` objects from a project's own declared
    sample dicts. Unknown keys are ignored; a missing `sample_id` is given a
    real, stable synthetic id (never a fabricated measurement) so a caller
    never has to invent per-sample ids just to declare a batch.
    """
    from .amba_performance_calculator import PerformanceSampleIR

    samples = []
    for i, entry in enumerate(declared):
        if not isinstance(entry, dict):
            raise ValueError(f"sample #{i} is not an object")
        kwargs = {k: v for k, v in entry.items() if k in _PERF_SAMPLE_FIELDS}
        kwargs.setdefault("sample_id", f"{id_prefix}-sample-{i}")
        samples.append(PerformanceSampleIR(**kwargs))
    return samples


def _read_amba_performance_state(root: Path,
                                  samples_path: Optional[Path] = None) -> Dict[str, Any]:
    """Real PortPerformanceIR/PathPerformanceIR rows for GET /api/amba-performance.

    The on-disk document is `{"ports": {"<port_id>": {"samples": [...],
    "latency_definition"?, "peak_bandwidth_bytes_per_second"?, "window_start"?,
    "window_end"?}, ...}, "paths": {"<path_id>": {"source_port", "dest_port",
    "samples": [...], "latency_definition"?, "window_start"?, "window_end"?},
    ...}}` -- every port/path entry is exactly
    `aggregate_port_performance()`'s own real keyword arguments. This function
    is a thin JSON-file front door onto that real builder, never a second
    performance-arithmetic engine: every bandwidth/throughput/latency/
    outstanding/stall-ratio/utilization field returned below is read straight
    off the real `PortPerformanceIR`/`PathPerformanceIR` that builder produces.
    """
    import dataclasses

    from .amba_performance_calculator import (PathPerformanceIR,
                                                PerformanceCalculatorError,
                                                aggregate_port_performance)

    path = Path(samples_path) if samples_path else _default_amba_performance_samples_path(root)
    empty = {"available": False, "samples_path": str(path), "ports": [],
             "paths": [], "rejected": [], "error": None}
    if not path.exists():
        return empty

    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return {**empty, "available": True,
                "error": {"reason": "MALFORMED_SAMPLES_FILE", "detail": {"message": str(e)}}}

    declared_ports = doc.get("ports") or {}
    declared_paths = doc.get("paths") or {}
    ports: List[Dict[str, Any]] = []
    paths: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []

    for port_id, entry in (declared_ports.items() if isinstance(declared_ports, dict) else []):
        if not isinstance(entry, dict):
            rejected.append({"kind": "port", "id": port_id, "reason": "PORT_ENTRY_NOT_AN_OBJECT"})
            continue
        try:
            samples = _perf_samples_from_declared(entry.get("samples") or [], str(port_id))
            port_ir = aggregate_port_performance(
                port_id, samples,
                latency_definition=entry.get("latency_definition"),
                peak_bandwidth_bytes_per_second=entry.get("peak_bandwidth_bytes_per_second"),
                window_start=entry.get("window_start"),
                window_end=entry.get("window_end"),
            )
        except (PerformanceCalculatorError, ValueError, TypeError) as e:
            rejected.append({"kind": "port", "id": port_id, "reason": str(e)})
            continue
        except Exception as e:
            rejected.append({"kind": "port", "id": port_id, "reason": f"UNEXPECTED_ERROR: {e}"})
            continue
        ports.append(dataclasses.asdict(port_ir))

    for path_id, entry in (declared_paths.items() if isinstance(declared_paths, dict) else []):
        if not isinstance(entry, dict):
            rejected.append({"kind": "path", "id": path_id, "reason": "PATH_ENTRY_NOT_AN_OBJECT"})
            continue
        source_port = entry.get("source_port")
        dest_port = entry.get("dest_port")
        if not source_port or not dest_port:
            rejected.append({"kind": "path", "id": path_id,
                              "reason": "MISSING_SOURCE_OR_DEST_PORT"})
            continue
        try:
            samples = _perf_samples_from_declared(entry.get("samples") or [], str(path_id))
            # Reuses the exact same real aggregation aggregate_port_performance()
            # already performs for a port -- bandwidth/throughput/latency
            # percentiles are pure functions of the samples, independent of
            # whether the id names a port or a source->dest path. Only the
            # subset of fields PathPerformanceIR actually declares is kept.
            agg = aggregate_port_performance(
                path_id, samples,
                latency_definition=entry.get("latency_definition"),
                window_start=entry.get("window_start"),
                window_end=entry.get("window_end"),
            )
            path_ir = PathPerformanceIR(
                path_id=path_id,
                source_port=source_port,
                dest_port=dest_port,
                sample_count=agg.sample_count,
                bandwidth=agg.bandwidth,
                throughput=agg.throughput,
                latency_report=agg.latency_report,
                source_evidence=agg.source_evidence,
            )
        except (PerformanceCalculatorError, ValueError, TypeError) as e:
            rejected.append({"kind": "path", "id": path_id, "reason": str(e)})
            continue
        except Exception as e:
            rejected.append({"kind": "path", "id": path_id, "reason": f"UNEXPECTED_ERROR: {e}"})
            continue
        paths.append(dataclasses.asdict(path_ir))

    return {
        "available": True,
        "samples_path": str(path),
        "ports": ports,
        "paths": paths,
        "rejected": rejected,
        "error": None,
    }


# --- AMBA Performance Trend View (GET /api/amba-performance-trend) ----------
# dashboard_amba_performance_trend_view: amba_performance_classification.py's
# compute_regression_delta()/detect_anomaly() already compare two real
# measured samples/periods (IMPROVED/REGRESSED/UNCHANGED/INCONCLUSIVE, and
# ANOMALY_DETECTED/NO_ANOMALY/UNKNOWN/NOT_APPLICABLE) -- but neither had ever
# been run across a project's own RECORDED SEQUENCE of periods, and nothing
# in this project rendered that as a trend a human can read.
#
# This reads a project's own declared per-metric period HISTORY off disk (the
# same `.dv-harness/amba/` convention the other AMBA cards above already use)
# and runs each consecutive pair of recorded periods straight through
# compute_regression_delta(), and every individual recorded period through
# detect_anomaly() -- never a second, dashboard-local trend-arithmetic
# engine. A metric with fewer than 2 recorded periods honestly reports
# INCONCLUSIVE (compute_regression_delta() itself needs two real measured
# samples to compare); a metric with zero recorded periods, or a project with
# no trend file at all, honestly reports NOT_AVAILABLE -- never a fabricated
# trend line synthesized from nothing.
#
# Read-only by design, same as the AMBA cards above: this renders real
# period-over-period comparisons a human reads -- nothing here decides a
# root cause, runs a build/simulation, or writes a verification verdict.
# This harness owns no live simulator; every value/period shown is
# caller-supplied evidence, never estimated.
def _default_amba_performance_trend_path(root: Path) -> Path:
    return root / ".dv-harness" / "amba" / "performance_trend.json"


def _read_amba_performance_trend_state(root: Path,
                                        trend_path: Optional[Path] = None) -> Dict[str, Any]:
    """Real RegressionDeltaResult/AnomalyDetectionResult rows across a
    metric's own recorded periods, for GET /api/amba-performance-trend.

    The on-disk document is `{"metrics": {"<metric_name>": {"lower_is_better"?,
    "improvement_threshold_percent"?, "periods": [{"period_id", "value"?,
    "window"?, "unit"?, "baseline_min"?, "baseline_max"?, "baseline_mean"?,
    "baseline_stddev"?, "deviation_threshold_stddev"?}, ...]}, ...}}`. Every
    consecutive pair drawn from one metric's own declared `periods` (in the
    caller's own declared order -- never re-sorted by a guessed date) is
    exactly `compute_regression_delta()`'s own real keyword arguments, and
    every individual period is exactly `detect_anomaly()`'s own real keyword
    arguments. This function is a thin JSON-file front door onto those two
    real builders, never a second trend-classification engine: every
    percent_change/verdict/deviation/status field returned below is read
    straight off the real `RegressionDeltaResult`/`AnomalyDetectionResult`
    those builders produce.
    """
    import dataclasses

    from .amba_performance_classification import (PerformanceClassificationError,
                                                     compute_regression_delta,
                                                     detect_anomaly)

    path = Path(trend_path) if trend_path else _default_amba_performance_trend_path(root)
    empty = {"available": False, "trend_path": str(path), "metrics": [], "rejected": [], "error": None}
    if not path.exists():
        return empty

    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return {**empty, "available": True,
                "error": {"reason": "MALFORMED_TREND_FILE", "detail": {"message": str(e)}}}

    declared = doc.get("metrics") or {}
    metrics: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []

    for metric_name, entry in (declared.items() if isinstance(declared, dict) else []):
        if not isinstance(entry, dict):
            rejected.append({"metric": metric_name, "reason": "METRIC_ENTRY_NOT_AN_OBJECT"})
            continue
        declared_periods = entry.get("periods")
        if declared_periods is None:
            declared_periods = []
        if not isinstance(declared_periods, list):
            rejected.append({"metric": metric_name, "reason": "PERIODS_NOT_A_LIST"})
            continue

        periods: List[Dict[str, Any]] = []
        for idx, p in enumerate(declared_periods):
            if not isinstance(p, dict) or not p.get("period_id"):
                rejected.append({"metric": metric_name,
                                  "reason": f"PERIOD_#{idx}_MISSING_PERIOD_ID_OR_NOT_AN_OBJECT"})
                continue
            periods.append(p)

        lower_is_better = entry.get("lower_is_better", True)
        improvement_threshold_percent = entry.get("improvement_threshold_percent")

        # Every RECORDED period is run through the real detect_anomaly() --
        # a period with no declared baseline honestly comes back
        # NOT_APPLICABLE (never a fabricated baseline), one with no declared
        # value honestly comes back UNKNOWN. This never depends on there
        # being a second period to compare against.
        anomalies: List[Dict[str, Any]] = []
        for p in periods:
            try:
                result = detect_anomaly(
                    p.get("value"),
                    baseline_min=p.get("baseline_min"),
                    baseline_max=p.get("baseline_max"),
                    baseline_mean=p.get("baseline_mean"),
                    baseline_stddev=p.get("baseline_stddev"),
                    deviation_threshold_stddev=p.get("deviation_threshold_stddev"),
                )
            except PerformanceClassificationError as e:
                rejected.append({"metric": metric_name, "period": p.get("period_id"),
                                  "reason": f"ANOMALY: {e}"})
                continue
            except Exception as e:
                rejected.append({"metric": metric_name, "period": p.get("period_id"),
                                  "reason": f"ANOMALY_UNEXPECTED_ERROR: {e}"})
                continue
            row = dataclasses.asdict(result)
            row["period_id"] = p.get("period_id")
            anomalies.append(row)

        # compute_regression_delta() needs TWO real measured periods -- one
        # call per consecutive pair, in the caller's own declared order.
        deltas: List[Dict[str, Any]] = []
        for i in range(1, len(periods)):
            prev, cur = periods[i - 1], periods[i]
            try:
                result = compute_regression_delta(
                    metric_name,
                    prev.get("value"),
                    cur.get("value"),
                    baseline_window=prev.get("window"),
                    current_window=cur.get("window"),
                    baseline_unit=prev.get("unit"),
                    current_unit=cur.get("unit"),
                    lower_is_better=lower_is_better,
                    improvement_threshold_percent=improvement_threshold_percent,
                )
            except PerformanceClassificationError as e:
                rejected.append({"metric": metric_name,
                                  "period": f"{prev.get('period_id')}->{cur.get('period_id')}",
                                  "reason": f"REGRESSION_DELTA: {e}"})
                continue
            except Exception as e:
                rejected.append({"metric": metric_name,
                                  "period": f"{prev.get('period_id')}->{cur.get('period_id')}",
                                  "reason": f"REGRESSION_DELTA_UNEXPECTED_ERROR: {e}"})
                continue
            row = dataclasses.asdict(result)
            row["baseline_period_id"] = prev.get("period_id")
            row["current_period_id"] = cur.get("period_id")
            deltas.append(row)

        # Honest, never-fabricated trend status: no recorded periods at all,
        # or only one, means compute_regression_delta() literally cannot
        # produce a real delta -- reported as such, never silently omitted
        # and never a synthesized trend line.
        if len(periods) == 0:
            trend_status, trend_reason = "NOT_AVAILABLE", (
                "no recorded periods declared for this metric -- no history "
                "exists to trend, never fabricated")
        elif len(periods) == 1:
            trend_status, trend_reason = "INCONCLUSIVE", (
                "only one recorded period declared -- compute_regression_delta() "
                "requires two real measured periods to compare")
        else:
            trend_status, trend_reason = "AVAILABLE", None

        metrics.append({
            "metric_name": metric_name,
            "periods_recorded": len(periods),
            "trend_status": trend_status,
            "trend_reason": trend_reason,
            "lower_is_better": bool(lower_is_better),
            "improvement_threshold_percent": improvement_threshold_percent,
            "deltas": deltas,
            "anomalies": anomalies,
        })

    metrics.sort(key=lambda m: m["metric_name"])

    return {
        "available": True,
        "trend_path": str(path),
        "metrics": metrics,
        "rejected": rejected,
        "error": None,
    }


# --- Research / Continuous Capability Evolution center (GUI-10) -------------
# dashboard.py had zero references to the research/capability-evolution path
# even though CLAUDE.md's "Research Front Door" / "Research Stage Boundaries"
# sections describe it as installed and permanent: capability_evolution.py owns
# the CapabilityEvolutionCandidate state machine, its candidates already live on
# the ONE Blackboard topic capability_evolution.BLACKBOARD_TOPIC, and its Human
# Approval Gate is already the real ControlPlane keyed on
# capability_evolution.HUMAN_APPROVAL_STAGE.
#
# Every value below is READ from that module -- the candidates through
# read_candidates(), the per-promotion-state totals through the Blackboard's own
# capability_evolution_counts(), the approval state through
# human_approval_status(), and which actions a candidate may legally take next
# through LEGAL_TRANSITIONS. Nothing is re-derived here, so this card cannot
# show a recommendation, a state or an approval that disagrees with what the
# real gate enforces.
#
# The three buttons are Stage-3 governance actions and go out through
# POST /api/control -> _dispatch_control() -> commands.cmd_research_* --
# the SAME dispatch every other Human Control Plane verb on this page uses.
# There is deliberately no research-specific POST endpoint and no second
# approval store: `dv-harness approve RESEARCH_CAPABILITY_EVOLUTION` from a
# terminal and the Approve button here write the identical control.json record.
RESEARCH_AUDIT_RECORD_LIMIT = 25


def _read_research_state(root: Path) -> Dict[str, Any]:
    """Real CapabilityEvolutionCandidate records + the real Human Approval Gate
    state for GET /api/research.

    An empty Blackboard topic is an honest empty state (`available: false`),
    never an invented candidate -- the same contract GET /api/coverage and
    GET /api/amba hold to. A topic that exists but cannot be interpreted
    reports its real reason rather than a 500, because "which candidate is
    malformed" is what the reviewer needs.
    """
    from . import capability_evolution as ce
    from .blackboard import Blackboard

    empty = {"available": False, "blackboard_topic": ce.BLACKBOARD_TOPIC,
             "candidates": [], "counts": None, "approval": None,
             "promotion_states": list(ce.PROMOTION_STATES),
             "recommendations": list(ce.RECOMMENDATIONS),
             "audit_records": [], "error": None}
    try:
        approval = ce.human_approval_status(root)
    except Exception as e:
        return {**empty, "error": {"reason": "APPROVAL_STATE_UNREADABLE",
                                   "detail": {"message": str(e)}}}
    empty["approval"] = approval

    try:
        items = ce.read_candidates(root)
        counts = Blackboard(root).capability_evolution_counts()
    except Exception as e:
        return {**empty, "error": {"reason": "CANDIDATE_TOPIC_UNREADABLE",
                                   "detail": {"message": str(e)}}}
    if not items:
        return empty

    by_recommendation: Dict[str, int] = {}
    rows: List[Dict[str, Any]] = []
    for candidate_id in sorted(items):
        c = items[candidate_id] if isinstance(items[candidate_id], dict) else {}
        status = c.get("current_status")
        recommendation = str(c.get("recommendation") or "UNKNOWN")
        by_recommendation[recommendation] = by_recommendation.get(recommendation, 0) + 1
        try:
            unanswered = ce.unanswered_l5_check_questions(c)
        except Exception as e:
            # A candidate the real module cannot interpret is reported AS that,
            # per-row -- one bad record must not blank the whole card.
            unanswered = [f"UNREADABLE: {e}"]
        rows.append({
            "candidate_id": candidate_id,
            "affected_capability": c.get("affected_capability"),
            "recommendation": recommendation,
            "overlap_status": c.get("overlap_status"),
            "current_status": status,
            "final_decision": c.get("final_decision"),
            "confidence": (c.get("confidence") or {}).get("level"),
            "experiment_required": c.get("experiment_required"),
            "hypothesis": c.get("hypothesis"),
            "proposed_action": c.get("proposed_action"),
            "exact_gap": c.get("exact_gap"),
            "decision_rationale": c.get("decision_rationale"),
            "evidence_refs": list(c.get("evidence_refs") or []),
            "unanswered_l5_questions": unanswered,
            # Which governance states this candidate may legally reach next,
            # straight off capability_evolution.LEGAL_TRANSITIONS -- so a button
            # the state machine would refuse is never offered as if it worked.
            "legal_transitions": list(ce.LEGAL_TRANSITIONS.get(status, ())),
            "status_history": list(c.get("status_history") or []),
        })

    try:
        audit = ce.candidate_audit_records(root)[:RESEARCH_AUDIT_RECORD_LIMIT]
    except Exception as e:
        audit = [{"kind": "AUDIT_TRAIL_UNREADABLE", "message": str(e)}]

    return {**empty, "available": True, "candidates": rows,
            "counts": {**counts, "by_recommendation": by_recommendation},
            "audit_records": audit}


# --- Generation Readiness Center (GET /api/generation-readiness) -----------
# A dashboard card surfacing generation_readiness.py's real 20-row Generation
# Readiness Matrix (section 211), following the exact same card-rendering
# convention this file already uses for the Protocols/AMBA/Research cards
# above rather than inventing a fourth: a thin `_read_*_state()` reader with
# the honest {"available", "error"} contract, one GET endpoint that reads it,
# and a fetch-once + client-side-render card in the served HTML/JS.
#
# This function computes NOTHING itself -- it is a straight call into
# generation_readiness.derive_generation_readiness(), which is itself
# read-only (see that module's own "WHAT THIS MODULE IS NOT" docstring
# section: no stage is run, no gate invoked, no build/regression/LSF job
# started, no governance state written). A GenerationReadinessError raised by
# the underlying module (a row whose declared fact_source no longer resolves
# through the import system, an unknown readiness class returned by a probe)
# is surfaced as this endpoint's own error reason/detail -- the same contract
# _read_amba_registry_state()/_read_research_state() already hold to -- rather
# than a bare 500, since this is a read of a computed artifact, not a client
# request body.
def _read_generation_readiness_state(root: Path, *, deep: bool = True) -> Dict[str, Any]:
    """Section 211's real twenty-row matrix for GET /api/generation-readiness.

    `deep` mirrors the CLI's own `--no-deep` flag: False skips the expensive
    SYS-1..SYS-30 cross-subsystem topology chain, and the Flow-B topology/
    command rows then report UNKNOWN with that as their recorded reason --
    every other row's verdict is unaffected either way."""
    from .generation_readiness import GenerationReadinessError, derive_generation_readiness

    try:
        matrix = derive_generation_readiness(root, deep=deep)
    except GenerationReadinessError as e:
        return {"available": False, "matrix": None,
                "error": {"reason": e.reason, "detail": e.detail}}
    except Exception as e:
        return {"available": False, "matrix": None,
                "error": {"reason": "GENERATION_READINESS_UNREADABLE",
                          "detail": {"message": str(e)}}}
    return {"available": True, "matrix": matrix, "error": None}


# --- Self-Learning Readiness (GET /api/self-learning-readiness) ------------
# GUI card surfacing self_learning_readiness.py's real, auto-generated 22-row
# section-55 SELF-LEARNING READINESS MATRIX -- a different row set over
# different sources from /api/generation-readiness just above (research/
# capability-evolution and five-tier-memory surfaces, never repeating any of
# that card's twenty rows), following the exact same
# fetch-real-artifact-and-render convention _read_generation_readiness_state()
# already established rather than a dashboard-local re-derivation of any row.
#
# This function computes NOTHING itself -- it is a straight call into
# self_learning_readiness.derive_self_learning_readiness(), which is itself
# read-only by its own documented "WRITES NO STATE and RUNS NOTHING" contract:
# no candidate is filed, no experiment is run, no memory record is added,
# retracted or confirmed, no approval is minted. A SelfLearningReadinessError
# raised by the underlying module (a row whose declared fact_source no longer
# resolves through the import system, a probe returning an unknown readiness
# class) is surfaced as this endpoint's own error reason/detail -- the same
# contract _read_generation_readiness_state() already holds to -- rather than
# a bare 500.
def _read_self_learning_readiness_state(root: Path) -> Dict[str, Any]:
    """self_learning_readiness.derive_self_learning_readiness()'s own real
    22-row matrix for GET /api/self-learning-readiness, computed live on
    every request -- never a dashboard-local re-derivation of any row. See
    the module comment above."""
    from .self_learning_readiness import SelfLearningReadinessError, derive_self_learning_readiness

    try:
        matrix = derive_self_learning_readiness(root)
    except SelfLearningReadinessError as e:
        return {"available": False, "matrix": None,
                "error": {"reason": e.reason, "detail": e.detail}}
    except Exception as e:
        return {"available": False, "matrix": None,
                "error": {"reason": "SELF_LEARNING_READINESS_UNREADABLE",
                          "detail": {"message": str(e)}}}
    return {"available": True, "matrix": matrix, "error": None}


# --- Confidence Calibration (GET /api/confidence-calibration) --------------
# GUI card surfacing confidence_calibration.py's real per-tier reliability
# report -- does a confidence tier's real track record in this project's own
# Memory records match the CONFIRMED > HIGH > MEDIUM > LOW ordering this
# harness acts on -- following the exact same fetch-real-artifact-and-render
# convention _read_generation_readiness_state() above already established,
# rather than a dashboard-local re-derivation of any tier's finding.
#
# This function computes NOTHING itself: it is a straight, read-only call
# into confidence_calibration.calibrate(root), which is itself read-only by
# its own documented contract -- a project with no memory store on disk is
# reported NOT_AVAILABLE WITHOUT constructing a MemoryStore (whose
# constructor would mkdir() the tier tree and write an empty index.json), so
# merely asking whether a project is calibrated must never mint the store
# being asked about. A CalibrationConfigError raised by the underlying
# module (an unknown declared tier, an out-of-range declared floor) is
# surfaced as this endpoint's own error reason/detail -- the same contract
# _read_generation_readiness_state()/_read_amba_registry_state() already
# hold to -- rather than a bare 500.
def _read_confidence_calibration_state(root: Path) -> Dict[str, Any]:
    """confidence_calibration.calibrate()'s own real per-tier report for
    GET /api/confidence-calibration, computed live on every request -- never
    a dashboard-local re-derivation of a tier's reliability/ordering
    finding. See the module comment above."""
    from .confidence_calibration import CalibrationConfigError, calibrate

    try:
        report = calibrate(root)
    except CalibrationConfigError as e:
        return {"available": False, "report": None,
                "error": {"reason": e.reason, "detail": e.detail}}
    except Exception as e:
        return {"available": False, "report": None,
                "error": {"reason": "CONFIDENCE_CALIBRATION_UNREADABLE",
                          "detail": {"message": str(e)}}}
    return {"available": True, "report": report, "error": None}


# --- Cross-Project Pattern Mining (GET /api/cross-project-mining) ----------
# GUI card surfacing cross_project_mining.py's real VI-2 recurring-pattern
# miner -- following the exact same fetch-real-artifact-and-render convention
# _read_confidence_calibration_state() above already established, rather than
# a dashboard-local re-derivation of any signature/project/transferable-fix
# finding.
#
# This function computes NOTHING itself: `production_status()` and
# `mine_cross_project_patterns()` are both read-only by their own documented
# contract (see cross_project_mining.py's own module docstring -- "a PURE
# READ over N project roots plus a small registry naming them"; mining
# "writes nothing to any memory tier, no candidate is filed, no approval is
# minted"). `ProjectRegistry.roots()` is read straight off this host's own
# `.dv-harness/cross_project/registry.json` -- no project is registered or
# unregistered from this card, and there is deliberately no write endpoint of
# its own here, matching every other read-only card on this page. A
# CrossProjectRegistryError raised by the underlying module (a registry file
# that is not readable JSON) is surfaced as this endpoint's own error
# reason/detail -- the same contract _read_generation_readiness_state()/
# _read_confidence_calibration_state() already hold to -- rather than a bare
# 500.
def _read_cross_project_mining_state(root: Path) -> Dict[str, Any]:
    """cross_project_mining.py's own real VI-2 status + mining report for
    GET /api/cross-project-mining, computed live on every request -- never a
    dashboard-local re-derivation of a project count or a cross-project
    pattern. See the module comment above."""
    from .cross_project_mining import (
        CrossProjectRegistryError,
        ProjectRegistry,
        mine_cross_project_patterns,
        production_status,
    )

    try:
        status = production_status(root)
        roots = ProjectRegistry(root).roots()
        mining = mine_cross_project_patterns(roots)
    except CrossProjectRegistryError as e:
        return {"available": False, "status": None, "mining": None,
                "error": {"reason": "CROSS_PROJECT_REGISTRY_UNREADABLE",
                          "detail": {"message": str(e)}}}
    except Exception as e:
        return {"available": False, "status": None, "mining": None,
                "error": {"reason": "CROSS_PROJECT_MINING_UNREADABLE",
                          "detail": {"message": str(e)}}}
    return {"available": True, "status": status, "mining": mining, "error": None}


# --- Verification Strategy Optimizer (GET /api/verification-strategy) ------
# GUI card surfacing verification_strategy.py's real VI-4 recommendation
# report -- which strategy (simulation/formal/PSS/emulation/FPGA prototype)
# this project's own real coverage-closure/failure-density/protocol/topology
# signals indicate, and which of those this harness can actually EXECUTE --
# following the exact same fetch-real-artifact-and-render convention
# _read_generation_readiness_state()/_read_confidence_calibration_state()
# above already established, rather than inventing a new one.
#
# This function computes NOTHING itself: it is a straight, read-only call
# into verification_strategy.execute_verb(), which is itself real-signal-
# only and read-only by its own documented contract (no build/job/approval
# is ever touched, and a RECOMMEND_ONLY strategy is never presented as
# something this harness can run -- see that module's own "WHAT THIS MODULE
# IS NOT" docstring section). `execute_verb()`'s own non-zero exit codes are
# never treated as HTTP errors here: exit 2 means "this report recommends a
# strategy this harness cannot execute", a real, renderable finding, not a
# server failure -- the identical "the module's own verdict vocabulary
# decides the payload, not this endpoint's plumbing" contract every sibling
# `_read_*_state()` above already holds to.
def _read_verification_strategy_state(root: Path, *, verb: str = "recommend",
                                        goal: str = "", scope: Optional[str] = None,
                                        protocol: Optional[str] = None,
                                        holes_path: Optional[str] = None) -> Dict[str, Any]:
    """verification_strategy.execute_verb()'s own real report for
    GET /api/verification-strategy, computed live on every request -- never
    a dashboard-local re-derivation of a signal, verdict, or executability
    row. See the module comment above."""
    from . import verification_strategy as _vs

    try:
        code, payload, _text = _vs.execute_verb(
            root, verb, goal=goal, scope=scope or _vs.SCOPE_UNDECLARED,
            protocol=protocol, holes_path=holes_path)
    except Exception as e:
        return {"available": False, "report": None,
                "error": {"reason": "VERIFICATION_STRATEGY_UNREADABLE",
                          "detail": {"message": str(e)}}}
    if code == 1:
        # A bad invocation the module itself refused (an unknown verb/scope,
        # an unreadable/unparseable/malformed --holes file) -- surfaced as
        # this endpoint's own named error, matching the "the module decides
        # what a failure means" contract every sibling reader above holds to,
        # rather than a bare 500.
        return {"available": False, "report": None,
                "error": {"reason": payload.get("error", "VERIFICATION_STRATEGY_BAD_REQUEST"),
                          "detail": payload}}
    # code 0 (a completed report) and code 2 (a completed report that
    # recommends a strategy this harness cannot execute) are both real,
    # renderable payloads -- never distinguished at this layer, matching
    # verification_strategy.py's own documentation that exit 2 is "a
    # CI-visible signal, never an approval in either direction", not an
    # HTTP-layer failure.
    return {"available": True, "report": payload, "error": None}


# --- Integration Proof Ladder (GET /api/system-smoke-proof) -----------------
# GUI card surfacing system_build_proof.py's real smoke-proof ladder (section
# 206: Build -> Elaborate -> Boot -> Shared-Resource -> One-Subsystem ->
# Two-Subsystem -> End-to-End -> WAVE -> Scoreboard -> SYSTEM_READY) for a
# project that has ALREADY RUN it -- following the exact same fetch-real-
# artifact-and-render convention _read_generation_readiness_state() above
# already established, rather than inventing a new one.
#
# system_build_proof.run_system_smoke_proof() needs real inputs this
# dashboard has no way to gather on its own (composed source sets, a system
# filelist, an fsdb path, an evidence-db job id -- see that module's own
# docstring). subsystem_maturity_gate.py's and generation_readiness.py's own
# real consumers of this ladder never re-run it either: both consume an
# already-produced `system_build_proof.SmokeProofReport.to_dict()` JSON a
# caller supplies. This endpoint does the identical thing: it reads whatever
# a real `dv-harness system-smoke-proof --json > <path>` (or
# `python -m dv_harness.system_build_proof --json > <path>`) run already
# wrote to this project's own conventional
# `.dv-harness/system_build_proof/smoke_proof_report.json` -- never a
# dashboard-local re-derivation of a single rung's status, and never a live
# re-run of the ladder itself. No report on disk yet is an honest
# {"available": False} naming the real path this endpoint looked for and the
# real CLI command that would produce it -- never a fabricated ladder.
def _default_smoke_proof_report_path(root: Path) -> Path:
    return root / ".dv-harness" / "system_build_proof" / "smoke_proof_report.json"


def _read_smoke_proof_state(root: Path, report_path: Optional[Path] = None) -> Dict[str, Any]:
    """system_build_proof.SmokeProofReport.to_dict()'s own real ladder for
    GET /api/system-smoke-proof, read verbatim off disk -- see the module
    comment above. A malformed or structurally-foreign report file is
    surfaced as this endpoint's own reason/detail rather than a bare 500,
    the same contract _read_generation_readiness_state() already holds to."""
    from . import system_build_proof as sbp

    p = Path(report_path) if report_path else _default_smoke_proof_report_path(root)
    empty = {"available": False, "report_path": str(p), "report": None, "error": None}
    if not p.exists():
        return empty

    try:
        report = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        return {**empty, "available": True,
                "error": {"reason": "MALFORMED_SMOKE_PROOF_REPORT_FILE",
                          "detail": {"message": str(e)}}}

    if not isinstance(report, dict) or "rungs" not in report or "verdict" not in report:
        return {**empty, "available": True,
                "error": {"reason": "NOT_A_SMOKE_PROOF_REPORT",
                          "detail": {"message": "the file on disk is not a "
                                     "system_build_proof.SmokeProofReport.to_dict() "
                                     "document (missing 'verdict'/'rungs')"}}}
    if report.get("verdict") not in sbp.SMOKE_VERDICTS:
        return {**empty, "available": True,
                "error": {"reason": "UNRECOGNIZED_SMOKE_PROOF_VERDICT",
                          "detail": {"verdict": report.get("verdict"),
                                     "known_verdicts": list(sbp.SMOKE_VERDICTS)}}}

    return {"available": True, "report_path": str(p), "report": report, "error": None}


# --- Design Knowledge Explorer (GET /api/design-knowledge) ------------------
# GUI card surfacing design_knowledge_correlation.py's real cross-source
# CONFLICT / GAP / DOCUMENTED_VS_IMPLEMENTED findings and the Design Knowledge
# Graph (sources / facts / provenance) as a browsable table -- following the
# exact same fetch-real-artifact-and-render convention _read_amba_registry_
# state() and _read_generation_readiness_state() above already established,
# rather than inventing a fifth.
#
# design_knowledge_correlation.py is deliberately a GENERIC engine over
# caller-supplied `sources` (see that module's own docstring: it imports
# NOTHING from dv_harness and never discovers a project's own facts itself --
# "a caller sitting in front of a real producer would build this shape from
# that producer's own real output"). So there is no live derive_*() this
# endpoint could call the way /api/generation-readiness does; the honest
# thing to surface is whatever a real upstream extraction step already
# assembled and wrote to this project's own conventional
# `.dv-harness/design_knowledge/sources.json` (+ optional
# `expected_facts.json`) -- this function then calls the REAL, unmodified
# `design_knowledge_correlation.correlate()` on it, live, on every request
# (a pure, cheap, deterministic function -- no I/O, no simulation, no build
# of its own), never a dashboard-local re-derivation of any conflict/gap/
# doc-vs-impl finding or graph node. No sources.json on disk yet is an
# honest {"available": False} naming the real file this endpoint looked for
# and the real CLI (`python -m dv_harness.design_knowledge_correlation
# --sources ... [--expected-facts ...] --json`) that would let a human
# inspect the identical computation directly -- never a fabricated graph.
def _default_design_knowledge_sources_path(root: Path) -> Path:
    return root / ".dv-harness" / "design_knowledge" / "sources.json"


def _default_design_knowledge_expected_facts_path(root: Path) -> Path:
    return root / ".dv-harness" / "design_knowledge" / "expected_facts.json"


def _read_design_knowledge_state(root: Path,
                                  sources_path: Optional[Path] = None,
                                  expected_facts_path: Optional[Path] = None) -> Dict[str, Any]:
    """design_knowledge_correlation.correlate()'s real report for
    GET /api/design-knowledge, computed live off a real on-disk sources.json
    (+ optional expected_facts.json) -- see the module comment above.

    A malformed sources/expected-facts file, or a `sources` shape
    correlate() itself refuses (DesignKnowledgeCorrelationError), is
    surfaced as this endpoint's own reason/detail rather than a bare 500 --
    the same contract _read_generation_readiness_state() already holds to."""
    from . import design_knowledge_correlation as dkc

    sp = Path(sources_path) if sources_path else _default_design_knowledge_sources_path(root)
    ep = Path(expected_facts_path) if expected_facts_path else _default_design_knowledge_expected_facts_path(root)
    empty = {"available": False, "sources_path": str(sp), "expected_facts_path": str(ep),
             "report": None, "error": None}
    if not sp.exists():
        return empty

    try:
        sources = json.loads(sp.read_text(encoding="utf-8"))
    except Exception as e:
        return {**empty, "available": True,
                "error": {"reason": "MALFORMED_SOURCES_FILE", "detail": {"message": str(e)}}}

    expected_facts = None
    if ep.exists():
        try:
            expected_facts = json.loads(ep.read_text(encoding="utf-8"))
        except Exception as e:
            return {**empty, "available": True,
                    "error": {"reason": "MALFORMED_EXPECTED_FACTS_FILE", "detail": {"message": str(e)}}}

    try:
        report = dkc.correlate(sources, expected_facts)
    except dkc.DesignKnowledgeCorrelationError as e:
        return {**empty, "available": True,
                "error": {"reason": "DESIGN_KNOWLEDGE_CORRELATION_INVALID_INPUT",
                          "detail": {"message": str(e)}}}
    except Exception as e:
        return {**empty, "available": True,
                "error": {"reason": "DESIGN_KNOWLEDGE_CORRELATION_FAILED",
                          "detail": {"message": str(e)}}}

    return {"available": True, "sources_path": str(sp), "expected_facts_path": str(ep),
            "report": report, "error": None}


# --- Requirement/vPlan Center (GET /api/requirement-vplan-center) -----------
# GUI card surfacing requirement_contract.py's own real
# analyze_requirement_contract_set() report and vplan_artifact.py's real
# NINE-dimension VPlanCompletenessReport + FIFTEEN-value gap taxonomy --
# following the exact same fetch-real-artifact-and-render convention
# _read_generation_readiness_state()/_read_design_knowledge_state() above
# already established, rather than inventing a sixth.
#
# Neither requirement_contract.py nor vplan_artifact.py discovers a
# project's own requirement/vplan records itself -- both take a plain
# caller-supplied record list (see each module's own docstring: no fixed
# producer path for either artifact exists in this repo yet, the same
# reason design_knowledge_correlation.py's own sources.json convention
# exists). So this endpoint reads whatever a real upstream extraction step
# already wrote to this project's own conventional
# .dv-harness/requirement_vplan/requirements.json (a bare list of
# requirement_contract-shaped records, or {"requirements": [...]}) and
# .dv-harness/requirement_vplan/vplan.json (a bare list of vplan_artifact
# row dicts, or {"vplan_rows": [...]}), then calls the REAL, unmodified
# analyze_requirement_contract_set()/analyze_vplan_completeness() on them,
# live, on every request -- never a dashboard-local re-derivation of any
# status/gap/finding. Neither file on disk yet is an honest
# {"available": False} naming the two real files this endpoint looked for
# and the real CLI entry points (`python -m dv_harness.requirement_contract`
# / `python -m dv_harness.vplan_artifact`) that would let a human inspect
# the identical computation directly -- never a fabricated table.
def _default_requirement_vplan_requirements_path(root: Path) -> Path:
    return root / ".dv-harness" / "requirement_vplan" / "requirements.json"


def _default_requirement_vplan_vplan_path(root: Path) -> Path:
    return root / ".dv-harness" / "requirement_vplan" / "vplan.json"


def _read_requirement_vplan_center_state(root: Path,
                                          requirements_path: Optional[Path] = None,
                                          vplan_path: Optional[Path] = None) -> Dict[str, Any]:
    """requirement_contract.analyze_requirement_contract_set() +
    vplan_artifact.analyze_vplan_completeness()'s real reports for
    GET /api/requirement-vplan-center, computed live off real on-disk
    requirements.json/vplan.json -- see the module comment above.

    A malformed requirements/vplan file, or a shape either real module
    itself refuses (VPlanArtifactValidationError), is surfaced as this
    endpoint's own reason/detail rather than a bare 500 -- the same contract
    every sibling _read_*_state() function above already holds to. Absent
    real evidence for one half (e.g. no vplan.json, only requirements.json)
    that half's report stays honestly None -- never a fabricated pass for
    the artifact nobody supplied."""
    from . import requirement_contract as rc
    from . import vplan_artifact as va

    rp = Path(requirements_path) if requirements_path else _default_requirement_vplan_requirements_path(root)
    vp = Path(vplan_path) if vplan_path else _default_requirement_vplan_vplan_path(root)
    empty = {"available": False, "requirements_path": str(rp), "vplan_path": str(vp),
             "requirement_report": None, "vplan_report": None, "error": None}
    if not rp.exists() and not vp.exists():
        return empty

    def _load(p: Path, wrapper_key: str):
        raw = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and wrapper_key in raw:
            raw = raw[wrapper_key]
        if not isinstance(raw, list):
            raise ValueError(
                "expected a bare list or {\"%s\": [...]}, got %s" % (wrapper_key, type(raw).__name__))
        return raw

    requirements = None
    if rp.exists():
        try:
            requirements = _load(rp, "requirements")
        except Exception as e:
            return {**empty, "available": True,
                    "error": {"reason": "MALFORMED_REQUIREMENTS_FILE", "detail": {"message": str(e)}}}

    vplan_rows = None
    if vp.exists():
        try:
            vplan_rows = _load(vp, "vplan_rows")
        except Exception as e:
            return {**empty, "available": True,
                    "error": {"reason": "MALFORMED_VPLAN_FILE", "detail": {"message": str(e)}}}

    requirement_report = None
    if requirements is not None:
        try:
            requirement_report = rc.analyze_requirement_contract_set(requirements)
            # analyze_requirement_contract_set() itself returns only
            # {"analyzed", "status_counts", "findings"} -- the per-requirement
            # row list a table needs is built here from the SAME real,
            # unmodified derive_status()/downstream_consumable() calls that
            # set already relies on internally, never a second re-derivation
            # of what COMPLETE/PARTIAL/... actually means.
            per_requirement = []
            for record in requirements:
                if not rc.declares_contract_shape(record):
                    continue
                derived_status, derived_reason = rc.derive_status(record)
                consumable, consumable_reason = rc.downstream_consumable(record)
                per_requirement.append({
                    "requirement_id": record.get("requirement_id"),
                    "declared_status": record.get("status"),
                    "derived_status": derived_status,
                    "derived_reason": derived_reason,
                    "downstream_consumable": consumable,
                    "downstream_consumable_reason": consumable_reason,
                })
            requirement_report["requirements"] = per_requirement
        except Exception as e:
            return {**empty, "available": True,
                    "error": {"reason": "REQUIREMENT_CONTRACT_ANALYSIS_FAILED", "detail": {"message": str(e)}}}

    vplan_report = None
    if vplan_rows is not None:
        # vplan_artifact.py's own module docstring names this exact
        # {"id": rec.requirement_id} reduction as the documented conversion
        # for a real requirement_contract.py record set -- never a second,
        # independently-derived shape.
        req_for_vplan = ([{"id": r.get("requirement_id")} for r in requirements]
                          if requirements is not None else None)
        try:
            report = va.analyze_vplan_completeness(vplan_rows, requirements=req_for_vplan, root=str(root))
            vplan_report = va.vplan_completeness_report_to_dict(report)
            # GAP_SEVERITY is a module-level lookup table, not a per-gap-dict
            # field -- carried alongside so the card can render each gap's
            # real severity without a second, dashboard-local copy of it.
            vplan_report["gap_severity"] = dict(va.GAP_SEVERITY)
        except va.VPlanArtifactValidationError as e:
            return {**empty, "available": True,
                    "error": {"reason": "VPLAN_ARTIFACT_VALIDATION_FAILED", "detail": {"message": str(e)}}}
        except Exception as e:
            return {**empty, "available": True,
                    "error": {"reason": "VPLAN_COMPLETENESS_ANALYSIS_FAILED", "detail": {"message": str(e)}}}

    return {"available": True, "requirements_path": str(rp), "vplan_path": str(vp),
            "requirement_report": requirement_report, "vplan_report": vplan_report, "error": None}


# --- Question Queue (GET /api/question-queue, POST /api/control QUESTION_ANSWER/
# QUESTION_REVOKE) -----------------------------------------------------------
# GUI card surfacing question_queue.py's real 3-tier ask-a-human queue -- pending
# (OPEN/ASSUMED) questions, each question's own real 9-field escalation package
# (question_queue.build_escalation_package()), recently recorded decisions, and the
# real Part-B tracking metrics (QuestionQueueStore.compute_metrics()) -- following the
# exact same fetch-real-artifact-and-render convention _read_generation_readiness_
# state()/_read_requirement_vplan_center_state() above already established, rather
# than inventing a new one. Answering/revoking a decision from this card goes out
# through the EXISTING POST /api/control dispatch (new QUESTION_ANSWER/QUESTION_REVOKE
# commands in _dispatch_control(), below), calling QuestionQueueStore.answer_question()/
# revoke_decision() verbatim -- the SAME writes `dv-harness question-queue answer`/
# `revoke` already perform, and the SAME sanctioned "a human answered" write path
# dv_harness/gui_intake_control_plane.py's own standalone server already uses. This
# module never re-derives the 3-tier classification, the digest/metrics arithmetic, or
# the escalation-package assembly -- every value rendered here is question_queue.py's
# own, read (or, for the two new POST commands, written) verbatim.
def _read_question_queue_state(root: Path) -> Dict[str, Any]:
    """question_queue.py's own real pending-question/decision/metrics state for
    GET /api/question-queue. Read-only: constructing a QuestionQueueStore performs no
    file I/O on its own, and every method called here is a real, existing READ --
    compute_metrics() never mutates the store; build_digest() (which does) is
    deliberately NOT called from this GET-poll path."""
    from . import question_queue

    try:
        store = question_queue.QuestionQueueStore(root)
        all_questions = store.list_questions()
    except Exception as e:
        return {"available": False,
                "error": {"reason": "QUESTION_QUEUE_UNREADABLE", "detail": {"message": str(e)}}}

    pending = [q for q in all_questions if q.get("status") in ("OPEN", "ASSUMED")]
    pending.sort(key=lambda q: q.get("created_at") or "", reverse=True)

    packages: Dict[str, Any] = {}
    for q in pending:
        try:
            packages[q["id"]] = question_queue.build_escalation_package(q)
        except Exception as e:
            packages[q["id"]] = {"error": str(e)}

    # ASSUMED (Tier-2 auto-assumption) and ANSWERED (a real human answer) both mean a
    # real decision is on file for that question's own question_key -- the field
    # POST /api/control QUESTION_REVOKE targets, per QuestionQueueStore.revoke_decision().
    decisions = [q for q in all_questions if q.get("status") in ("ASSUMED", "ANSWERED")]
    decisions.sort(key=lambda q: q.get("answered_at") or q.get("created_at") or "", reverse=True)

    try:
        metrics = store.compute_metrics()
    except Exception as e:
        metrics = {"error": str(e)}

    # Best-effort: question_queue.list_clarification_requests() is read-only (never mints
    # store.clarifications_path) but is included in a try/except anyway, matching every
    # other real, existing read in this function -- a clarification-read failure must
    # never sink the whole card.
    try:
        clarifications = question_queue.list_clarification_requests(store)
    except Exception:
        clarifications = []

    return {
        "available": True,
        "total_questions": len(all_questions),
        "pending_questions": pending,
        "escalation_packages": packages,
        "decisions": decisions[:50],
        "clarifications": clarifications,
        "metrics": metrics,
        "error": None,
    }


# --- Evidence Integrity / Signoff Blockers (GET /api/evidence-integrity-signoff-blockers) ---
# GUI card surfacing evidence_integrity_states.py's real project-wide VALID/STALE/
# SUPERSEDED/CONTRADICTED/CORRUPT/UNKNOWN rollup and signoff_blocker_list.py's real
# 12-dimension CLOSED/NOT_CLOSED/INCOMPLETE_EVIDENCE signoff-blocker rollup -- following
# the exact same fetch-real-artifact-and-render convention _read_generation_readiness_
# state() above already established, rather than inventing a new one.
#
# Unlike design_knowledge_correlation.py/requirement_contract.py/vplan_artifact.py (all
# deliberately generic engines needing a caller-populated sources.json convention), BOTH
# evidence_integrity_states.py and signoff_blocker_list.py take a real project `root`
# directly and read this project's own real evidence.duckdb / signoff freeze store /
# waiver ledger / functional-coverage evidence themselves -- so this endpoint calls both
# LIVE on every request, exactly like /api/generation-readiness calls
# derive_generation_readiness(root) live, never a dashboard-local re-derivation of
# either module's own verdict. signoff_blocker_list.derive_signoff_blockers() is handed
# the ALREADY-computed evidence-integrity report so it never re-runs that classification
# a second time internally -- there is exactly one evidence-integrity computation per
# request, not two.
def _read_evidence_integrity_signoff_blocker_state(root: Path) -> Dict[str, Any]:
    """evidence_integrity_states.classify_project_evidence_integrity() +
    signoff_blocker_list.derive_signoff_blockers()'s real reports for
    GET /api/evidence-integrity-signoff-blockers, computed live off this project's own
    real evidence.duckdb / signoff freeze store / waiver ledger / functional-coverage
    evidence -- see the module comment above.

    Neither module needs a project to have any evidence recorded at all: an empty
    project reports a real, honest NOT_AVAILABLE/INCOMPLETE_EVIDENCE verdict rather than
    raising, exactly like /api/generation-readiness's own bare-project behavior. Only a
    genuine exception (e.g. a corrupt evidence.duckdb) is surfaced as this endpoint's own
    reason/detail rather than a bare 500 -- the same contract every sibling
    _read_*_state() function above already holds to."""
    from . import evidence_integrity_states as eis
    from . import signoff_blocker_list as sbl

    try:
        integrity_report = eis.classify_project_evidence_integrity(root)
    except Exception as e:
        return {"available": True, "integrity_report": None, "blocker_report": None,
                "error": {"reason": "EVIDENCE_INTEGRITY_CLASSIFICATION_FAILED",
                          "detail": {"message": str(e)}}}

    try:
        blocker_report = sbl.derive_signoff_blockers(root, evidence_integrity_report=integrity_report)
    except Exception as e:
        return {"available": True, "integrity_report": integrity_report, "blocker_report": None,
                "error": {"reason": "SIGNOFF_BLOCKER_DERIVATION_FAILED",
                          "detail": {"message": str(e)}}}

    return {"available": True, "integrity_report": integrity_report,
            "blocker_report": blocker_report, "error": None}


# --- Test Suite Center (GET /api/test-suite-center) -------------------------
# GUI card surfacing test_suite_lifecycle.py's real per-pattern lifecycle
# state (GENERATED through CLOSURE_PROVEN, plus the caller-declared
# SEMANTIC_DUPLICATE/SUBSUMED/SUPERSET relationship tags) -- following the
# exact same fetch-real-artifact-and-render convention _read_generation_
# readiness_state()/_read_requirement_vplan_center_state() above already
# established, rather than inventing an eighth.
#
# test_suite_lifecycle.py discovers no project fact itself beyond what is
# already real and queryable in this project's own evidence.duckdb
# (evidence_db.py's jobs/regression_verdicts tables, golden_scenario.py's
# capsule store) -- it opens that real database READ-ONLY and derives every
# pattern's own lifecycle state from it directly, live, on every request.
# The three relationship tags have no real producer anywhere in this
# codebase (no pattern-similarity/dedup engine exists) and are therefore
# NEVER derived here either -- they are read only from a caller-declared,
# evidence-cited fact this project's own conventional
# .dv-harness/test_suite/relationships.json may supply (the same "accept an
# explicit caller-declared fact the real evidence store cannot supply,
# rather than invent one" discipline design_knowledge_correlation.py's
# sources.json and requirement_vplan's requirements.json/vplan.json already
# establish). No evidence.duckdb on disk yet is an honest
# {"available": False} naming the real database path this endpoint looked
# for and the real CLI (`python -m dv_harness.test_suite_lifecycle --json`)
# that would let a human inspect the identical computation directly --
# never a fabricated table.
def _default_test_suite_relationships_path(root: Path) -> Path:
    return root / ".dv-harness" / "test_suite" / "relationships.json"


def _read_test_suite_center_state(root: Path,
                                   relationships_path: Optional[Path] = None,
                                   db_path: Optional[Path] = None) -> Dict[str, Any]:
    """test_suite_lifecycle.derive_test_suite_lifecycle()'s real report for
    GET /api/test-suite-center, computed live off the real on-disk
    evidence.duckdb (+ an optional real relationships.json) -- see the
    module comment above.

    A malformed relationships.json file, or a relationship fact
    test_suite_lifecycle.py itself refuses (TestSuiteLifecycleError -- an
    uncited relationship, an unrecognized relation, or a pattern this
    project's own evidence.duckdb has no real row for at all), is surfaced
    as this endpoint's own reason/detail rather than a bare 500 -- the same
    contract every sibling _read_*_state() function above already holds
    to."""
    from . import test_suite_lifecycle as tsl

    relp = Path(relationships_path) if relationships_path else _default_test_suite_relationships_path(root)
    relationships = None
    if relp.exists():
        try:
            raw = json.loads(relp.read_text(encoding="utf-8"))
        except Exception as e:
            return {"available": False, "relationships_path": str(relp),
                    "report": None, "reason": None,
                    "error": {"reason": "MALFORMED_RELATIONSHIPS_FILE", "detail": {"message": str(e)}}}
        relationships = raw.get("relationships") if isinstance(raw, dict) else raw
        if not isinstance(relationships, list):
            return {"available": False, "relationships_path": str(relp),
                    "report": None, "reason": None,
                    "error": {"reason": "MALFORMED_RELATIONSHIPS_FILE",
                              "detail": {"message": "expected a bare list or "
                                         "{\"relationships\": [...]}, got %s" % type(relationships).__name__}}}

    try:
        result = tsl.derive_test_suite_lifecycle(root, db_path=db_path, relationships=relationships)
    except tsl.TestSuiteLifecycleError as e:
        return {"available": False, "relationships_path": str(relp), "report": None, "reason": None,
                "error": {"reason": "TEST_SUITE_LIFECYCLE_INVALID_INPUT", "detail": {"message": str(e)}}}
    except Exception as e:
        return {"available": False, "relationships_path": str(relp), "report": None, "reason": None,
                "error": {"reason": "TEST_SUITE_LIFECYCLE_FAILED", "detail": {"message": str(e)}}}

    return {"available": result["available"], "relationships_path": str(relp),
            "report": result.get("report"), "reason": result.get("reason"), "error": None}


# --- Subsystem Verification Center (GET /api/subsystem-system-verification) -
# GUI card surfacing subsystem_contract.py's/system_verification_contract.py's
# real assembled records plus ip_ownership_conflict.py's/system_resource_
# inventory.py's real compatibility findings -- following the exact same
# fetch-real-artifact-and-render convention _read_test_suite_center_state()/
# _read_requirement_vplan_center_state() above already established, rather
# than inventing a ninth.
#
# Unlike the design_knowledge/requirement_vplan cards, this card needs no
# caller-supplied file to do REAL work: subsystem_contract.
# assemble_subsystem_contract() and system_resource_inventory.
# real_cross_subsystem_findings() are both self-sufficient over this
# project's own real registered-subsystem set
# (environment_mode_router.read_registered_subsystem_entries(), written only
# on a gate-verified SIGNOFF PASS) and its own env.manifest.json/
# evidence.duckdb/waiver ledger -- called live, on every request, never
# re-derived here. The optional .dv-harness/subsystem_system_verification/
# inputs.json overlay supplies the handful of facts this repo has no fixed
# producer path for yet (a caller-declared legacy_bfm_declarations/
# connectivity_rows per subsystem for ip_ownership_conflict.py -- that
# module's own docstring: "there is no real producer for this fact in this
# codebase" -- and a real system_topology_analysis.py-/system_command_
# plan.py-shaped document for system_verification_contract.py's own topology/
# command_registry sections, which that module deliberately never imports or
# derives itself) -- the same "accept an explicit caller-declared fact
# rather than invent one" convention design_knowledge_correlation.py's
# sources.json already establishes. Absent that overlay, those specific
# sections honestly report NOT_APPLICABLE/NOT_AVAILABLE rather than a
# fabricated pass; nothing here mints an approval, runs a stage, or invokes a
# gate -- every one of the four underlying modules is READ-ONLY by its own
# documented contract.
def _default_subsystem_system_verification_inputs_path(root: Path) -> Path:
    return root / ".dv-harness" / "subsystem_system_verification" / "inputs.json"


def _read_subsystem_system_verification_state(root: Path,
                                               inputs_path: Optional[Path] = None) -> Dict[str, Any]:
    """subsystem_contract.assemble_subsystem_contract() +
    system_verification_contract.assemble_system_verification_contract() +
    ip_ownership_conflict.analyze_ip_ownership_conflict() +
    system_resource_inventory.real_cross_subsystem_findings()'s real reports
    for GET /api/subsystem-system-verification, computed live off this
    project's own real registered-subsystem set (+ an optional real
    subsystem_system_verification/inputs.json overlay) -- see the module
    comment above.

    A malformed inputs.json, or a shape one of the four underlying modules
    itself refuses, is surfaced per-subsystem in `errors` rather than a bare
    500 or a silently-dropped subsystem -- the same contract every sibling
    _read_*_state() function above already holds to."""
    from . import subsystem_contract as sc
    from . import system_verification_contract as svc
    from . import system_resource_inventory as sri
    from . import ip_ownership_conflict as ioc
    from . import environment_mode_router as emr
    from . import env_manifest as em

    ip_path = Path(inputs_path) if inputs_path else _default_subsystem_system_verification_inputs_path(root)
    overlay: Dict[str, Any] = {}
    if ip_path.exists():
        try:
            overlay = json.loads(ip_path.read_text(encoding="utf-8"))
            if not isinstance(overlay, dict):
                raise ValueError("expected a JSON object, got %s" % type(overlay).__name__)
        except Exception as e:
            return {"available": True, "inputs_path": str(ip_path), "inputs_supplied": True,
                    "error": {"reason": "MALFORMED_INPUTS_FILE", "detail": {"message": str(e)}},
                    "system_name": None, "subsystem_names": [], "subsystem_contracts": [],
                    "system_verification_contract": None, "ip_ownership_conflicts": {},
                    "cross_subsystem_findings": None, "errors": []}

    system_name = overlay.get("system_name")
    per_subsystem_overlay = overlay.get("per_subsystem") or {}
    declared_subsystems = overlay.get("subsystems")

    try:
        registry_entries = emr.read_registered_subsystem_entries(root)
    except Exception:
        registry_entries = []

    subsystem_names = (list(declared_subsystems) if declared_subsystems is not None
                        else [e.get("name") for e in registry_entries if e.get("name")])

    subsystem_contract_records: List[Dict[str, Any]] = []
    ip_ownership_reports: Dict[str, Any] = {}
    errors: List[Dict[str, Any]] = []

    def _resolve_manifest_path(name: Optional[str], override: Optional[str]) -> Optional[Path]:
        if override:
            return Path(override)
        if name:
            entry = next((e for e in registry_entries
                          if str(e.get("name", "")).strip().lower() == str(name).strip().lower()), None)
            if entry and entry.get("environment_manifest"):
                cand = Path(str(entry["environment_manifest"]))
                cand = cand if cand.is_absolute() else (root / cand)
                if cand.is_file():
                    return cand
        return em.default_manifest_path(root)

    def _assemble_one(name: Optional[str]) -> None:
        sub_overlay = (per_subsystem_overlay.get(name, {}) if name
                       else (overlay.get("project_scope") or {}))
        try:
            record = sc.assemble_subsystem_contract(
                root, subsystem=name,
                manifest_path=sub_overlay.get("manifest_path"),
                requirements_path=sub_overlay.get("requirements_path"),
                db_path=sub_overlay.get("db_path"),
                declared_spec_version=sub_overlay.get("declared_spec_version"),
            )
            subsystem_contract_records.append(record)
        except Exception as e:
            errors.append({"subsystem": name, "stage": "subsystem_contract", "message": str(e)})

        manifest_path = _resolve_manifest_path(name, sub_overlay.get("manifest_path"))
        key = name or "__project__"
        if not manifest_path or not manifest_path.is_file():
            ip_ownership_reports[key] = {"status": ioc.STATUS_NOT_APPLICABLE,
                                          "reason": "NO_ENV_MANIFEST_FOUND"}
            return
        try:
            manifest = em.load_env_manifest(manifest_path)
            ip_ownership_reports[key] = ioc.analyze_ip_ownership_conflict(
                manifest,
                legacy_bfm_declarations=sub_overlay.get("legacy_bfm_declarations"),
                connectivity_rows=sub_overlay.get("connectivity_rows"),
            )
        except Exception as e:
            errors.append({"subsystem": name, "stage": "ip_ownership_conflict", "message": str(e)})

    if subsystem_names:
        for name in subsystem_names:
            _assemble_one(name)
    else:
        # No registered/declared subsystems at all -- assemble the
        # project-scope contract (subsystem=None), the common case this
        # repo's own USB example represents, per subsystem_contract.py's own
        # docstring.
        _assemble_one(None)

    # system_resource_inventory.py's real compatibility findings -- self-
    # sufficient over the real registered subsystem set (or the caller's own
    # declared selection); CROSSCHECK_UNAVAILABLE (never a fabricated
    # "clear") when fewer than two subsystems resolve.
    try:
        cross_subsystem_findings = sri.real_cross_subsystem_findings(
            root, selected=(subsystem_names or None))
    except Exception as e:
        cross_subsystem_findings = {"status": sri.CROSSCHECK_UNAVAILABLE,
                                     "reason": "ANALYSIS_RAISED: %s" % e}

    try:
        sv_record = svc.assemble_system_verification_contract(
            subsystem_contracts=(subsystem_contract_records or None),
            system_topology=overlay.get("system_topology"),
            system_resource_registry=cross_subsystem_findings,
            system_command_registry=overlay.get("system_command_registry"),
            system_name=system_name,
        )
    except Exception as e:
        sv_record = None
        errors.append({"subsystem": None, "stage": "system_verification_contract", "message": str(e)})

    return {
        "available": True, "inputs_path": str(ip_path), "inputs_supplied": ip_path.exists(),
        "error": None, "system_name": system_name, "subsystem_names": subsystem_names,
        "subsystem_contracts": subsystem_contract_records,
        "system_verification_contract": sv_record,
        "ip_ownership_conflicts": ip_ownership_reports,
        "cross_subsystem_findings": cross_subsystem_findings,
        "errors": errors,
    }


# --- System Transaction View + End-to-End Scoreboard --------------------
# GET /api/system-transaction-e2e-scoreboard
# GUI card surfacing amba_transaction_ir.py's real 22-field transaction
# shape (composed cross-subsystem via system_transaction_ir.py),
# transaction_correlation_ir.py's real correlated/reconstructed logical
# AXI transaction records, and system_scoreboard_ir.py's real system-scope
# scoreboard-composition (end-to-end coverage) facts -- following the exact
# same fetch-real-artifact-and-render convention _read_design_knowledge_
# state()/_read_subsystem_system_verification_state() above already
# established, rather than inventing an eighth.
#
# None of the three underlying modules discovers a project's own facts
# itself (see each module's own docstring: subsystem_fabrics/system_
# transaction_links, requests/responses/data_transactions/beats/
# transactions, and system_interactions/existing_scoreboards are all
# entirely caller-declared, evidence-cited facts). So this endpoint reads
# whatever a real upstream step already wrote to this project's own
# conventional .dv-harness/system_transaction_e2e_scoreboard/inputs.json
# and calls the REAL, unmodified builder for each of the three sections
# independently, live, on every request -- never a dashboard-local
# re-derivation of any composed field, correlation verdict, or scoreboard-
# coverage finding. A malformed inputs.json, or a shape one section's own
# builder refuses, is surfaced in that section's own 'error' rather than a
# bare 500 or a silently-dropped section -- the same contract every
# sibling _read_*_state() function above already holds to. No file on
# disk yet is an honest {"available": False} naming the real file this
# endpoint looked for and the three real CLI entry points
# (`python -m dv_harness.system_transaction_ir` /
# `python -m dv_harness.transaction_correlation_ir` /
# `python -m dv_harness.system_scoreboard_ir`) that would let a human
# inspect the identical computation directly -- never a fabricated table.
#
# Disclosed residual: transaction_correlation_ir.reconstruct_logical_
# transactions()'s optional `burst_linkage_by_ref` argument expects real
# `BurstLinkageEntry` dataclass instances (it reads `.parent_ref`/`.status`/
# `.evidence` as attributes, not dict keys) -- a JSON overlay can only ever
# supply plain dicts, so this endpoint never threads that argument through;
# a project genuinely needing burst-split/merge linkage in this composed
# record inspects `python -m dv_harness.transaction_correlation_ir
# reconstruct` directly.
def _default_system_transaction_e2e_scoreboard_inputs_path(root: Path) -> Path:
    return root / ".dv-harness" / "system_transaction_e2e_scoreboard" / "inputs.json"


def _read_system_transaction_e2e_scoreboard_state(
        root: Path, inputs_path: Optional[Path] = None) -> Dict[str, Any]:
    """system_transaction_ir.build_system_transaction_ir() +
    transaction_correlation_ir.correlate_responses()/associate_data_beats()/
    reconstruct_logical_transactions() + system_scoreboard_ir.
    build_system_scoreboard_ir()'s real reports for
    GET /api/system-transaction-e2e-scoreboard, computed live off a real
    on-disk inputs.json overlay -- see the module comment above."""
    from . import system_transaction_ir as sti
    from . import transaction_correlation_ir as tci
    from . import system_scoreboard_ir as ssi

    p = Path(inputs_path) if inputs_path else _default_system_transaction_e2e_scoreboard_inputs_path(root)
    empty = {"available": False, "inputs_path": str(p),
             "system_transaction": None, "transaction_correlation": None,
             "system_scoreboard": None, "error": None}
    if not p.exists():
        return empty

    try:
        overlay = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(overlay, dict):
            raise ValueError("expected a JSON object, got %s" % type(overlay).__name__)
    except Exception as e:
        return {**empty, "available": True,
                "error": {"reason": "MALFORMED_INPUTS_FILE", "detail": {"message": str(e)}}}

    # --- System Transaction (amba_transaction_ir.py's 22-field shape, ---
    # --- composed cross-subsystem) --------------------------------------
    st_overlay = overlay.get("system_transaction") or {}
    try:
        st_ir = sti.build_system_transaction_ir(
            st_overlay.get("subsystem_fabrics"),
            st_overlay.get("system_transaction_links"),
        )
        system_transaction: Dict[str, Any] = {
            "report": st_ir.to_dict(),
            "markdown": sti.render_system_transaction_markdown(st_ir),
            "error": None,
        }
    except Exception as e:
        system_transaction = {"report": None, "markdown": None,
                               "error": {"reason": "SYSTEM_TRANSACTION_BUILD_FAILED",
                                         "detail": {"message": str(e)}}}

    # --- Transaction Correlation (real correlated / reconstructed --------
    # --- logical AXI transaction records) --------------------------------
    tc_overlay = overlay.get("transaction_correlation") or {}
    try:
        response_entries = tci.correlate_responses(
            tc_overlay.get("requests") or [], tc_overlay.get("responses") or [])
        data_report = tci.associate_data_beats(
            tc_overlay.get("data_transactions") or [], tc_overlay.get("beats") or [])
        logical_entries = tci.reconstruct_logical_transactions(
            tc_overlay.get("transactions") or [], response_entries, data_report)
        transaction_correlation: Dict[str, Any] = {
            "logical_transactions": [e.to_dict() for e in logical_entries],
            "response_correlation": [e.to_dict() for e in response_entries],
            "data_association": data_report.to_dict(),
            "markdown": tci.render_logical_transaction_report(logical_entries),
            "error": None,
        }
    except Exception as e:
        transaction_correlation = {
            "logical_transactions": None, "response_correlation": None,
            "data_association": None, "markdown": None,
            "error": {"reason": "TRANSACTION_CORRELATION_BUILD_FAILED",
                      "detail": {"message": str(e)}},
        }

    # --- System Scoreboard (end-to-end scoreboard-placement facts) -------
    ss_overlay = overlay.get("system_scoreboard") or {}
    try:
        ss_ir = ssi.build_system_scoreboard_ir(
            ss_overlay.get("system_interactions"),
            ss_overlay.get("existing_scoreboards"),
        )
        system_scoreboard: Dict[str, Any] = {
            "report": ss_ir.to_dict(),
            "markdown": ssi.render_system_scoreboard_markdown(ss_ir),
            "error": None,
        }
    except Exception as e:
        system_scoreboard = {"report": None, "markdown": None,
                              "error": {"reason": "SYSTEM_SCOREBOARD_BUILD_FAILED",
                                        "detail": {"message": str(e)}}}

    return {
        "available": True, "inputs_path": str(p), "error": None,
        "system_transaction": system_transaction,
        "transaction_correlation": transaction_correlation,
        "system_scoreboard": system_scoreboard,
    }


# --- Verification Architecture View (GET /api/verification-architecture) ---
# GUI card surfacing verification_architecture.py's real
# assemble_verification_architecture() -- the 5 required matrices (VIP Bind,
# Interface-to-Verification, Function-to-Checker, Assertion Placement,
# Scoreboard Architecture) -- following the exact same fetch-real-artifact-
# and-render convention _read_design_knowledge_state()/_read_requirement_
# vplan_center_state() above already established, rather than inventing a
# seventh.
#
# verification_architecture.py discovers no project fact itself -- every one
# of assemble_verification_architecture()'s ~14 keyword arguments (vip_config,
# bind_entries, checker_links, scoreboard_entries, assertion_candidates,
# clock_reset, ...) is a caller-supplied real fact from env_manifest.py/
# connectivity.py/phy_boundary.py or a project's own declared linkage -- the
# same "no fixed producer path for this artifact yet" reason design_knowledge_
# correlation.py's sources.json and requirement_vplan's requirements.json/
# vplan.json conventions already exist. So this endpoint reads whatever a real
# upstream assembly step already wrote to this project's own conventional
# .dv-harness/verification_architecture/inputs.json (a bare dict whose keys
# are exactly assemble_verification_architecture()'s own keyword names -- see
# that function's own docstring for the shape; any key omitted defaults to
# that function's own empty-list/NOT_AVAILABLE default, never fabricated),
# then calls the REAL, unmodified assemble_verification_architecture() on it,
# live, on every request -- never a dashboard-local re-derivation of any IR
# field or matrix. The returned matrices are the SAME real markdown text
# render_vip_bind_matrix()/render_interface_to_verification_matrix()/
# render_function_to_checker_matrix()/render_assertion_placement_matrix()/
# render_scoreboard_architecture_matrix() already produce -- rendered here
# verbatim inside a <pre> block, matching this page's own established
# convention for a backend-rendered text report (stageProfileResult/
# auditResult), never re-tabulated in JS. No inputs.json on disk yet is an
# honest {"available": False} naming the real file this endpoint looked for
# and the real CLI (`python -m dv_harness.verification_architecture`) that
# would let a human inspect the identical computation directly -- never a
# fabricated matrix. The assembled document is additionally schema-validated
# against verification_architecture.schema.json before being served, matching
# that module's own fail-closed discipline, and the result carries never a
# guessed IR field -- the `_irs` convenience key (real Python IR objects, not
# JSON-serializable) is stripped before this endpoint returns anything.
def _default_verification_architecture_inputs_path(root: Path) -> Path:
    return root / ".dv-harness" / "verification_architecture" / "inputs.json"


def _read_verification_architecture_state(root: Path,
                                           inputs_path: Optional[Path] = None) -> Dict[str, Any]:
    """verification_architecture.assemble_verification_architecture()'s real
    document (5 matrices + both comparators) for
    GET /api/verification-architecture, computed live off a real on-disk
    inputs.json -- see the module comment above.

    A malformed inputs file, an inputs.json key assemble_verification_
    architecture() does not accept, a real VerificationArchitectureError
    (an invalid status/confidence value inside a raw IR-building dict), or a
    schema violation the assembled document itself carries is surfaced as
    this endpoint's own reason/detail rather than a bare 500 -- the same
    contract every sibling _read_*_state() function above already holds to."""
    from . import verification_architecture as va_mod

    ip = Path(inputs_path) if inputs_path else _default_verification_architecture_inputs_path(root)
    empty = {"available": False, "inputs_path": str(ip), "document": None, "error": None}
    if not ip.exists():
        return empty

    try:
        raw = json.loads(ip.read_text(encoding="utf-8"))
    except Exception as e:
        return {**empty, "available": True,
                "error": {"reason": "MALFORMED_INPUTS_FILE", "detail": {"message": str(e)}}}
    if not isinstance(raw, dict):
        return {**empty, "available": True,
                "error": {"reason": "MALFORMED_INPUTS_FILE",
                          "detail": {"message": f"expected a JSON object, got {type(raw).__name__}"}}}

    try:
        doc = va_mod.assemble_verification_architecture(**raw)
    except TypeError as e:
        return {**empty, "available": True,
                "error": {"reason": "MALFORMED_INPUTS_FILE", "detail": {"message": str(e)}}}
    except va_mod.VerificationArchitectureError as e:
        return {**empty, "available": True,
                "error": {"reason": "VERIFICATION_ARCHITECTURE_ANALYSIS_FAILED", "detail": {"message": str(e)}}}
    except Exception as e:
        return {**empty, "available": True,
                "error": {"reason": "VERIFICATION_ARCHITECTURE_ANALYSIS_FAILED", "detail": {"message": str(e)}}}

    doc.pop("_irs", None)
    try:
        va_mod.validate_verification_architecture(doc)
    except va_mod.VerificationArchitectureValidationError as e:
        return {**empty, "available": True,
                "error": {"reason": "VERIFICATION_ARCHITECTURE_SCHEMA_INVALID", "detail": {"message": str(e)}}}

    return {"available": True, "inputs_path": str(ip), "document": doc, "error": None}


# --- VIP/UVM Environment Builder + VIP Evidence View (GET /api/vip-environment-builder) ---
# GUI card surfacing protocol_capability.py's real per-protocol
# capability_status (the same real qualification/protocol_capability_
# registry.json the existing Protocols card already reads via
# _protocol_registry() -- reused here verbatim, never re-derived) alongside
# vip_api_card.py's real PROVEN/BLOCKED/UNPROVABLE citation report for a
# generated environment -- following the exact same fetch-real-artifact-and-
# render convention _read_verification_architecture_state() above already
# established, rather than inventing an eighth.
#
# vip_api_card.py discovers no project fact itself: validate_vip_api_usage()
# takes a caller-supplied source list and a real vip_symbol_index document
# (see that module's own docstring -- there is no fixed producer path for
# either artifact in this repo). So this endpoint reads whatever a real
# upstream step already wrote to this project's own conventional
# .dv-harness/vip_evidence/inputs.json (a bare dict carrying "sources"
# (generated .sv/.svh files/dirs to validate) and "index_path" (a real
# vip_symbol_index.build_symbol_index() document on disk), plus any of
# validate_vip_api_usage()'s own optional keyword names --
# "relative_to"/"vip_class_prefixes"/"extra_known_base_methods"), then calls
# the REAL, unmodified vip_api_card.load_index()/validate_vip_api_usage() on
# it, live, on every request -- never a dashboard-local re-derivation of any
# card's PROVEN/BLOCKED/UNPROVABLE status. No inputs.json on disk yet is an
# honest {"available": False} naming the real file this endpoint looked for
# and the real CLI (`python -m dv_harness.vip_api_card` /
# `dv-harness vip-api-check`) that would let a human inspect the identical
# computation directly -- never a fabricated card. The protocol registry is
# always returned even when no vip_evidence inputs.json exists yet, since it
# needs no upstream step at all -- it is the same real registry the Protocols
# card above already reads.
def _default_vip_environment_builder_inputs_path(root: Path) -> Path:
    return root / ".dv-harness" / "vip_evidence" / "inputs.json"


def _read_vip_environment_builder_state(root: Path,
                                         inputs_path: Optional[Path] = None) -> Dict[str, Any]:
    """protocol_capability.py's real per-protocol capability_status (reused
    via _protocol_registry(), never re-derived) plus
    vip_api_card.validate_vip_api_usage()'s real PROVEN/BLOCKED/UNPROVABLE
    citation report for GET /api/vip-environment-builder, the report computed
    live off a real on-disk inputs.json -- see the module comment above.

    A malformed inputs file, a missing "sources"/"index_path" key, an
    inputs.json key validate_vip_api_usage() does not accept, a missing/
    invalid index (VipApiValidationError), or any other real failure is
    surfaced as this endpoint's own reason/detail rather than a bare 500 --
    the same contract every sibling _read_*_state() function above already
    holds to."""
    from . import vip_api_card as vac

    protocols = _protocol_registry(root)
    ip = Path(inputs_path) if inputs_path else _default_vip_environment_builder_inputs_path(root)
    empty = {"available": False, "protocols": protocols, "inputs_path": str(ip),
             "report": None, "error": None}
    if not ip.exists():
        return empty

    try:
        raw = json.loads(ip.read_text(encoding="utf-8"))
    except Exception as e:
        return {**empty, "available": True,
                "error": {"reason": "MALFORMED_INPUTS_FILE", "detail": {"message": str(e)}}}
    if not isinstance(raw, dict):
        return {**empty, "available": True,
                "error": {"reason": "MALFORMED_INPUTS_FILE",
                          "detail": {"message": f"expected a JSON object, got {type(raw).__name__}"}}}

    sources = raw.get("sources")
    index_path = raw.get("index_path")
    if not sources or not index_path:
        return {**empty, "available": True,
                "error": {"reason": "MALFORMED_INPUTS_FILE",
                          "detail": {"message": "inputs.json must declare non-empty \"sources\" "
                                                 "and \"index_path\" keys"}}}

    try:
        index = vac.load_index(index_path)
    except vac.VipApiValidationError as e:
        return {**empty, "available": True,
                "error": {"reason": "VIP_SYMBOL_INDEX_UNAVAILABLE", "detail": {"message": str(e)}}}

    # Every remaining key is forwarded to validate_vip_api_usage() as its own
    # optional keyword args (relative_to/vip_class_prefixes/
    # extra_known_base_methods) -- a key that function does not accept raises
    # TypeError, surfaced below as a malformed-inputs error rather than a
    # bare 500.
    kwargs = {k: v for k, v in raw.items() if k not in ("sources", "index_path")}
    try:
        report = vac.validate_vip_api_usage(sources, index, **kwargs)
    except TypeError as e:
        return {**empty, "available": True,
                "error": {"reason": "MALFORMED_INPUTS_FILE", "detail": {"message": str(e)}}}
    except vac.VipApiValidationError as e:
        return {**empty, "available": True,
                "error": {"reason": "VIP_API_VALIDATION_FAILED", "detail": {"message": str(e)}}}
    except Exception as e:
        return {**empty, "available": True,
                "error": {"reason": "VIP_API_VALIDATION_FAILED", "detail": {"message": str(e)}}}

    return {"available": True, "protocols": protocols, "inputs_path": str(ip),
            "report": report.to_dict(), "error": None}


# --- Loop Engineering Center (LOOP-4, sections 107 + 108) -------------------
# Before this, dashboard.py's ONLY "loop" surface was the single-run/
# continuous-run Start toggle -- a control, not observability. Section 107
# requires the GUI to expose WHY a loop is running: its state, iteration,
# verified gain, budget, plateau/oscillation verdict and next action, with a
# drill-down. Nothing on this page could answer any of those.
#
# This function derives NONE of it. Every figure was computed by the mechanism
# that owns it -- loop_contract.derive_loop_state(),
# loop_convergence.classify_loop_convergence(), loop_budget's ledger, gates.py
# through the persisted stage status -- and reached the audit trail as the
# payload of one real section-108 event emitted by engine.DVHarness.loop().
# `loop_telemetry.read_loop_telemetry()` folds those events back into section
# 107's own eight columns and fourteen drill-down fields; this wrapper exists
# only so the endpoint reads like every other read-only GET on this server.
def _read_loop_engineering_state(root: Path, *, run_id: str = "") -> Dict[str, Any]:
    """Section 107's table for GET /api/loops, read-only.

    A project whose loops have never emitted a section-108 event reports the
    honest empty state `loop_telemetry` produces -- naming the events.jsonl it
    read and the real `dv-harness start --loop` that would populate it -- the
    same contract GET /api/coverage, /api/amba, /api/research and /api/memory
    already hold to. It never starts a loop, runs a stage, evaluates a gate,
    writes a file or mints an approval; polling it is a tail of an append-only
    log."""
    from . import loop_telemetry
    try:
        return loop_telemetry.read_loop_telemetry(root, run_id=run_id or None)
    except Exception as e:  # an unreadable audit trail is a real reason, not a 500
        return {"available": False, "rows": [], "sessions": {},
                "columns": [{"key": k, "label": l}
                            for k, l in loop_telemetry.SECTION_107_COLUMNS],
                "drilldown_fields": [{"key": k, "label": l}
                                     for k, l in loop_telemetry.SECTION_107_DRILLDOWN_FIELDS],
                "event_names": list(loop_telemetry.LOOP_TELEMETRY_EVENTS),
                "scan": {},
                "reason": f"LOOP_TELEMETRY_UNREADABLE: {type(e).__name__}: {e}"}


# --- Global Status Bar (Global Status Bar theme, sections 414-421/428) -----
# A persistent header shown across every page of this single-page dashboard
# (compact/standard/expanded layout modes; identity/harness/current-activity/
# execution/closure/blocker regions; a click-to-expand detail drawer),
# reading this batch's own HarnessStatusService via GET /api/status. Matches
# /api/loops'/`_read_loop_engineering_state()`'s own contract immediately
# above: read-only, and a real error from the underlying module is surfaced
# as this endpoint's own reason/detail rather than a bare 500.
def _read_harness_status_state(root: Path) -> Dict[str, Any]:
    """GET /api/status: one HarnessStatusIR snapshot, via
    `harness_status.HarnessStatusService(root).serve()`
    (aggregate -> normalize -> validate -> snapshot). Never a second,
    dashboard-local aggregation of harness state -- every field is exactly
    what that module's own real subsystem readers produced. A project this
    service has read nothing about yet reports every status-bearing field
    honestly UNKNOWN (GF-AT-28) rather than a fabricated READY; that is
    `serve()`'s own contract, not a special case handled here."""
    from .harness_status import HarnessStatusError, HarnessStatusService

    try:
        snapshot = HarnessStatusService(root).serve()
    except HarnessStatusError as e:
        return {"available": False, "status": None,
                "error": {"reason": str(e)}}
    except Exception as e:
        return {"available": False, "status": None,
                "error": {"reason": "HARNESS_STATUS_UNREADABLE",
                          "detail": {"message": str(e)}}}
    return {"available": True, "status": snapshot, "error": None}


def _external_gui_server_nav_routes(root: Path) -> "List[tuple]":
    """P2-2: real, evidence-based nav route entries out to the two existing
    standalone GUI intake servers this project already ships --
    `gui_intake_wizard.py` and `gui_intake_control_plane.py` -- closing the
    "no nav link, no shared shell" residual both modules' own CLAUDE.md
    sections disclose. Called ONLY from the NEW `/view/dashboard` route's own
    shell (see that route's own comment) -- never injected into the existing
    `/` page's markup, which stays completely untouched.

    Each entry is `(route_id, label, href)`, the exact 3-tuple
    `web_layout.render_nav()` already accepts -- no change to that function
    was needed or made. Every link is built from REAL, currently-checkable
    evidence, never an assumed/guessed target:

    - GUI Intake Control Plane genuinely persists its own real bound
      host/port (plus a session token) to
      `.dv-harness/intake_control_plane_session.json` at real server start
      (`gui_intake_control_plane.issue_session_token()`), so a real link is
      built from that file's own content when it exists. Absent it (the
      server has never been started against this project), the honest label
      says so and the href is the inert `"#"` -- never a guessed port.
    - GUI Intake Wizard persists NO host/port anywhere on disk -- its own
      `.dv-harness/gui_intake_wizard/session.json` is wizard CONVERSATIONAL
      state (current step index, answers), not server-listening evidence,
      confirmed by reading that module fresh before writing this function.
      The only real evidence available without editing that module (out of
      this item's own file-safety scope, which names only dashboard.py and
      web_layout.py) is a live, short-timeout TCP probe against its own
      documented `--port` CLI default (8799) -- a real, current
      connectivity check, never a fabricated "it is running" claim. A
      wizard actually running on a different port is honestly reported as
      not detected rather than guessed at.
    """
    routes: "List[tuple]" = []

    # --- GUI Intake Control Plane -----------------------------------------
    rec: Optional[Dict[str, Any]] = None
    try:
        from . import gui_intake_control_plane as _gicp
        session_path = _gicp.session_file(root)
        if session_path.exists():
            rec = json.loads(session_path.read_text(encoding="utf-8"))
    except Exception:
        rec = None
    port = rec.get("port") if isinstance(rec, dict) else None
    if isinstance(port, int) and port > 0:
        host = rec.get("host") if isinstance(rec.get("host"), str) and rec.get("host") else "127.0.0.1"
        token = rec.get("token") if isinstance(rec.get("token"), str) and rec.get("token") else None
        href = f"http://{host}:{port}/"
        if token:
            href += f"?token={urllib.parse.quote(token)}"
        routes.append(("gui_intake_control_plane",
                        "GUI Intake Control Plane (live)", href))
    else:
        routes.append(("gui_intake_control_plane",
                        "GUI Intake Control Plane (not running)", "#"))

    # --- GUI Intake Wizard -------------------------------------------------
    import socket
    wizard_host, wizard_port = "127.0.0.1", 8799  # gui_intake_wizard.py's own --port default
    wizard_live = False
    try:
        with socket.create_connection((wizard_host, wizard_port), timeout=0.2):
            wizard_live = True
    except OSError:
        wizard_live = False
    if wizard_live:
        routes.append(("gui_intake_wizard", "GUI Intake Wizard (live)",
                        f"http://{wizard_host}:{wizard_port}/"))
    else:
        routes.append(("gui_intake_wizard",
                        f"GUI Intake Wizard (not detected at default port {wizard_port})",
                        "#"))

    # --- GUI VIP Coverage Wizard (INTAKE-23, 2026-09-08) --------------------
    # The third of the three real intake GUI servers, and the one covering
    # the widest span (DUT/RTL discovery through functional coverage
    # signoff) -- but the only one this nav function did not already link,
    # leaving it discoverable only by a human already knowing to run
    # `python -m dv_harness.gui_vip_coverage_wizard` by hand. Unlike the
    # wizard above, this server's own `issue_session_token()` DOES persist
    # its real bound host/port (plus the token) to
    # `.dv-harness/gui_vip_coverage_wizard_session.json` at real server
    # start, so this uses the SAME real-evidence-from-disk approach as the
    # Control Plane entry above rather than a live TCP probe.
    rec = None
    try:
        from . import gui_vip_coverage_wizard as _gvcw
        session_path = root / ".dv-harness" / _gvcw.AUTH_SESSION_FILENAME
        if session_path.exists():
            rec = json.loads(session_path.read_text(encoding="utf-8"))
    except Exception:
        rec = None
    port = rec.get("port") if isinstance(rec, dict) else None
    if isinstance(port, int) and port > 0:
        host = rec.get("host") if isinstance(rec.get("host"), str) and rec.get("host") else "127.0.0.1"
        token = rec.get("token") if isinstance(rec.get("token"), str) and rec.get("token") else None
        href = f"http://{host}:{port}/"
        if token:
            href += f"?token={urllib.parse.quote(token)}"
        routes.append(("gui_vip_coverage_wizard", "GUI VIP Coverage Wizard (live)", href))
    else:
        routes.append(("gui_vip_coverage_wizard",
                        "GUI VIP Coverage Wizard (not running)", "#"))
    return routes


# --- Agent Activity / Observability (GUI-06) --------------------------------
# ULTIMATE_COMPLETE_GUI.md section 64 ("GUI-06 -- AGENT ACTIVITY /
# OBSERVABILITY") requires "Multi-Agent execution must not be an opaque black
# box" and names Agent/Current State/Current Action/Owned Task/Last Update as
# the columns to show. A 2026-09-06 cross-check of dashboard.py against that
# section (this same pass) found the gap was total: `multi_agent.py`'s
# AgentTaskStore is a REAL, production-wired per-stage delegation ledger --
# engine.py's run_stage() calls MultiAgentOrchestrator.delegate() before every
# LLM call and start_task()/complete_task() around the adapter run (see that
# module's own header NOTICE) -- and `.dv-harness/agents/ownership.json`
# records real fan-out branch resource claims via the same store's acquire()/
# release() -- but dashboard.py imported `multi_agent` NOWHERE and no card
# rendered either file. The only per-agent fact visible anywhere on this page
# was the Workflow Graph's node.agent label (which agent a STATIC graph node
# is assigned to), never which delegated task is RUNNING right now, what it
# is currently claiming, or how long it has been at it.
#
# This reads the two real files verbatim through the same _read_json_file()
# every other card on this page uses -- never by constructing a real
# AgentTaskStore, whose __init__ mkdir()s `.dv-harness/agents/` and seeds both
# files the first time it runs, which would mint that tree merely because a
# browser asked a question (the same discipline `golden_flow_readiness.py`/
# `confidence_calibration.py`'s own dashboard-adjacent siblings already state
# for the identical reason). A project that has never delegated a task reports
# the honest empty state below, never a fabricated agent.
#
# Deliberately excluded: a join to `.dv-harness/react/<node>/iteration_*.json`
# (the real per-attempt Hypothesis->Evidence->Confidence->Gap->Next-Best-Action
# record react.ReactRecorder.record() writes) for the Evidence/Confidence/
# Blocking Reason/Next-Best-Action columns section 64 also lists. Checked
# directly before writing this: AgentTaskStore.create_task() records `route`
# (the resolved SKILL route, e.g. "implementation-route") and `agent`, never
# the STAGE id, while react.record()'s `node` parameter IS the stage id
# (engine.py's run_stage() passes `node=stage`) -- there is no shared key
# between the two stores today, so correlating a task row to a react record by
# guessing (e.g. matching on agent name, or "the most recent one") would be
# exactly the fabricated-evidence-linkage the Evidence Truth Rule forbids.
# Section 64 itself only asks the GUI to "display where appropriate" -- Agent/
# Current State/Current Action/Owned Task/Last Update are real and shown;
# Evidence/Confidence/Blocking Reason/Next-Best-Action for the CURRENT stage
# are already real and visible elsewhere on this same page (the "Why (current
# stage)" card's blocking_reason/gate_verdict, the Findings tiles, and the
# Qualified Conclusion block in Hypothesis & Review) rather than duplicated
# here under an unproven per-task join.
def _default_agents_dir(root: Path) -> Path:
    return root / ".dv-harness" / "agents"


def _read_agent_activity_state(root: Path) -> Dict[str, Any]:
    """Real AgentTaskStore delegation/claim ledger for GET /api/agent-activity.

    `rows` is one entry per real delegated task in tasks.json (Agent/Current
    Action=route/Skills/Parallel Group/Current State=status/Last
    Update=started_at|completed_at|duration_sec), each carrying its own
    `owned_resources` -- the real blackboard-topic/resource names ownership.json
    currently attributes to that exact task_id (never a name match, never a
    guess: `rec.get("task_id") == t.get("task_id")` only). `available` is
    False only when tasks.json has never been written at all (this project has
    never delegated a real task) -- present-but-empty (`[]`) is a different,
    real fact and reports `available: True` with zero rows."""
    agents_dir = _default_agents_dir(root)
    tasks_path = agents_dir / "tasks.json"
    ownership_path = agents_dir / "ownership.json"

    tasks = _read_json_file(tasks_path, default=None)
    if not tasks_path.exists():
        return {"available": False, "tasks_path": str(tasks_path),
                "ownership_path": str(ownership_path), "rows": [],
                "summary": {"task_count": 0, "status_counts": {}, "claimed_resource_count": 0}}
    if not isinstance(tasks, list):
        tasks = []

    ownership = _read_json_file(ownership_path, default={})
    if not isinstance(ownership, dict):
        ownership = {}
    owned_by_task: Dict[str, List[str]] = {}
    for resource, rec in ownership.items():
        if not isinstance(rec, dict):
            continue
        tid = rec.get("task_id")
        if not tid:
            continue
        owned_by_task.setdefault(tid, []).append(resource)

    rows = []
    status_counts: Dict[str, int] = {}
    for t in tasks:
        if not isinstance(t, dict):
            continue
        status = str(t.get("status") or "UNKNOWN")
        status_counts[status] = status_counts.get(status, 0) + 1
        task_id = t.get("task_id")
        rows.append({
            "task_id": task_id,
            "agent": t.get("agent"),
            "route": t.get("route"),
            "skills": t.get("skills") or [],
            "parallel_group": t.get("parallel_group"),
            "depends_on": t.get("depends_on") or [],
            "status": status,
            "started_at": t.get("started_at"),
            "completed_at": t.get("completed_at"),
            "duration_sec": t.get("duration_sec"),
            "owned_resources": sorted(owned_by_task.get(task_id, [])),
        })
    # Newest-first by started_at (a not-yet-started task, started_at=None,
    # sorts last rather than crashing the comparison).
    rows.sort(key=lambda r: (r["started_at"] is None, -(r["started_at"] or 0)))

    return {
        "available": True,
        "tasks_path": str(tasks_path),
        "ownership_path": str(ownership_path),
        "rows": rows,
        "summary": {
            "task_count": len(rows),
            "status_counts": status_counts,
            "claimed_resource_count": len(ownership),
        },
    }


# --- Memory Hierarchy + Obsidian Knowledge Vault (GUI-11) -------------------
# dashboard.py had no surface at all for the 5-tier Memory Hierarchy
# (memory.MEMORY_LEVELS: working/job/project/engineering/organizational) or for
# the DV-Knowledge Vault memory_vault.py mirrors those records into. The
# "Shared Knowledge Center" card below is a DIFFERENT thing -- it reports the
# cross-project broker's config/connectivity, not what this project's own
# memory tiers hold -- so a reviewer had no way to answer "how much verified
# knowledge does this project actually carry, at which tier" from the GUI.
#
# Every number and every note below is READ from the real modules, never
# re-derived here:
#   - per-tier record counts come from MemoryStore.index_integrity(), the
#     SAME read-only drift report memory_doctor's `memory_store_index` check
#     uses (it also reports index-vs-file drift, which is exactly the failure
#     that once hid 18 of 31 engineering records from search -- see
#     MemoryStore._index_lock()'s comment);
#   - which tiers even HAVE a local file store is derived from
#     memory_router's own dispatch tables rather than restated, so
#     "organizational has no local store by design, its backing store IS the
#     shared Knowledge Center" cannot drift out of sync with the router;
#   - vault notes come from the real MemoryProvider (memory_vault.
#     get_active_provider()) through its own search()/read(). No markdown or
#     YAML frontmatter is parsed in this module.
MEMORY_VAULT_NOTE_LIMIT = 25
# The bucket-by-tier scan is one search() over the vault with an empty query
# (that adapter's own documented "list everything") rather than one search per
# tier. Bounded so a very large vault degrades into an honestly-flagged
# truncated count instead of an unbounded read on an HTTP thread.
MEMORY_VAULT_SCAN_LIMIT = 500


def _memory_store_dir(root: Path) -> Path:
    return root / ".dv-harness" / "memory"


def _locally_stored_memory_levels() -> set:
    """Which MEMORY_LEVELS tiers really have a `.dv-harness/memory/<level>/`
    file store, derived from memory_router's OWN destination dispatch tables.

    Deliberately derived rather than hardcoded: `organizational` is absent
    from both tables because route_and_store() sends ORGANIZATIONAL_MEMORY
    straight to OrganizationalMemoryStore (the shared, cross-user Knowledge
    Center) instead of falling into the generic MemoryStore dispatch -- see
    that branch's comment. Restating that design decision as a literal here
    would give it a second home that could silently disagree with the router."""
    from .memory_router import _STORE_LEVEL, _TIER_STORE_CLASSES
    return {cls.level for cls in _TIER_STORE_CLASSES.values()} | set(_STORE_LEVEL.values())


def _read_memory_center_state(root: Path, *, text_query: str = "",
                              level_filter: str = "",
                              limit: int = MEMORY_VAULT_NOTE_LIMIT,
                              note_id: str = "") -> Dict[str, Any]:
    """Real per-tier Memory Hierarchy counts + real vault note browse/search
    for GET /api/memory.

    A project that has never written a memory record and has no vault reports
    an honest empty state (`available: false`) naming both paths it looked at
    -- the same contract GET /api/coverage, /api/amba and /api/research hold
    to. A store or vault that exists but cannot be read reports its real
    reason rather than a 500.

    Read-only in intent: neither half is constructed unless its directory
    already exists, so polling this endpoint never materializes a memory store
    or a vault tree in a project that has neither. (Once a vault DOES exist,
    get_active_provider() runs bootstrap_vault(), which is additive-only
    mkdir(exist_ok=True) by its own contract and never touches an existing
    file -- that is the sanctioned factory every real caller uses, and
    constructing an adapter directly to dodge it would be the parallel
    mechanism this codebase forbids.)"""
    from .memory import MEMORY_LEVELS, MemoryStore, OrganizationalMemoryStore
    from . import memory_vault

    levels = list(MEMORY_LEVELS)
    query_echo = {"text": text_query, "memory_level": level_filter,
                  "limit": limit, "note": note_id}
    base = {"available": False, "levels": levels, "tiers": [],
            "store": None, "vault": None, "notes": [], "note_detail": None,
            "query": query_echo, "error": None}
    if level_filter and level_filter not in levels:
        return {**base, "error": {"reason": "UNKNOWN_MEMORY_LEVEL",
                                  "detail": {"memory_level": level_filter,
                                             "known_levels": levels}}}

    cfg = load_config(root)

    # -- tier half: the real local record stores --------------------------
    store_dir = _memory_store_dir(root)
    store: Dict[str, Any] = {"available": store_dir.exists(),
                             "store_dir": str(store_dir),
                             "index_integrity": None, "error": None}
    per_level: Dict[str, Any] = {}
    if store["available"]:
        try:
            integrity = MemoryStore(root).index_integrity()
        except Exception as e:
            store["error"] = {"reason": "MEMORY_STORE_UNREADABLE",
                              "detail": {"message": str(e)}}
        else:
            store["index_integrity"] = integrity
            per_level = integrity.get("per_level") or {}

    # -- vault half: the real Obsidian/filesystem knowledge vault ----------
    vault_path = memory_vault.resolve_vault_path(root, cfg)
    vault: Dict[str, Any] = {"available": vault_path.exists(),
                             "vault_path": str(vault_path),
                             "provider": None, "status": None, "detail": None,
                             "note_count": 0, "scan_limit": MEMORY_VAULT_SCAN_LIMIT,
                             "scan_truncated": False, "error": None}
    notes: List[Dict[str, Any]] = []
    note_detail: Optional[Dict[str, Any]] = None
    notes_by_level: Dict[str, int] = {}
    if vault["available"]:
        try:
            provider = memory_vault.get_active_provider(root, cfg)
            status = provider.status()
            vault["provider"] = status.get("provider")
            vault["status"] = status.get("status")
            vault["detail"] = status
            scan = provider.search({}, limit=MEMORY_VAULT_SCAN_LIMIT)
            if not scan.get("ok"):
                vault["error"] = {"reason": "VAULT_SEARCH_UNAVAILABLE",
                                  "detail": scan}
                scanned: List[Dict[str, Any]] = []
            else:
                scanned = list(scan.get("results") or [])
            vault["note_count"] = len(scanned)
            vault["scan_truncated"] = len(scanned) >= MEMORY_VAULT_SCAN_LIMIT
            for n in scanned:
                lv = str((n.get("frontmatter") or {}).get("memory_level") or "(unset)")
                notes_by_level[lv] = notes_by_level.get(lv, 0) + 1

            search_query: Dict[str, Any] = {}
            if text_query:
                search_query["text"] = text_query
            if level_filter:
                search_query["memory_level"] = level_filter
            if search_query:
                res = provider.search(search_query, limit=limit)
                if res.get("ok"):
                    notes = list(res.get("results") or [])
                else:
                    vault["error"] = {"reason": "VAULT_SEARCH_UNAVAILABLE",
                                      "detail": res}
            else:
                notes = scanned[:limit]

            if note_id:
                read = provider.read(note_id)
                note_detail = read if read.get("ok") else {
                    "ok": False, "note_id": note_id,
                    "error": read.get("error") or read.get("reason") or "NOT_FOUND"}
        except Exception as e:
            vault["error"] = {"reason": "VAULT_UNREADABLE",
                              "detail": {"message": str(e)}}

    # -- one row per tier, both halves joined ------------------------------
    local_levels = _locally_stored_memory_levels()
    try:
        kc_configured: Optional[bool] = OrganizationalMemoryStore(root, cfg=cfg).configured()
    except Exception as e:
        kc_configured = None
        base["error"] = {"reason": "ORGANIZATIONAL_BACKING_STORE_UNREADABLE",
                         "detail": {"message": str(e)}}

    tiers: List[Dict[str, Any]] = []
    for lv in levels:
        counts = per_level.get(lv) or {}
        row: Dict[str, Any] = {
            "level": lv,
            "has_local_store": lv in local_levels,
            "record_files": counts.get("files"),
            "index_rows": counts.get("index_rows"),
            "vault_notes": notes_by_level.get(lv, 0) if vault["available"] else None,
        }
        if lv in local_levels:
            row["backing_store"] = str(store_dir / lv)
        else:
            # memory_router.route_and_store()'s ORGANIZATIONAL_MEMORY branch:
            # no local file store by design, the shared Knowledge Center IS
            # the store. A local count of 0 here is that design, not "no
            # organizational knowledge exists" -- the card must not let those
            # two read the same.
            row["backing_store"] = "shared Knowledge Center (knowledge_center.KnowledgeCenterClient)"
            row["knowledge_center_configured"] = kc_configured
        tiers.append(row)

    return {**base,
            "available": bool(store["available"] or vault["available"]),
            "tiers": tiers, "store": store, "vault": vault,
            "notes": notes, "note_detail": note_detail}


# --- FSDB structured evidence panel (fsdbreport -csv) ----------------------
# Poster-compliance audit (2026-08-29): fsdb_report.py's run_fsdbreport()/
# parse_fsdbreport_output() had zero dashboard/GUI callers -- GET
# /api/fsdb-report below wires the confirmed-real invocation
# (`fsdbreport f.fsdb -period <T> -level 1 -csv`, dv-workflow/SKILL.md's
# 2026-08-29 "Confirmed drift" entry) up to a queryable, structured
# text-evidence table. Deliberately NOT a waveform/timeline renderer --
# FSDB is a proprietary binary format with no public library, so a real
# signal-timeline viewer is out of scope (see this feature's design doc).
def _run_and_parse_fsdb_report(fsdb_path: str, period: str = "", hier: str = "") -> Dict[str, Any]:
    """Runs the real fsdbreport binary (via fsdb_report.run_fsdbreport(),
    the one external-process boundary -- never mocked in production code)
    against fsdb_path with the confirmed-real `-period <T> -level 1 -csv`
    flags, then parses its stdout with fsdb_report.parse_fsdbreport_output().
    `hier` is accepted and echoed back for visibility, but NOT translated
    into a guessed CLI flag: the confirmed invocation above does not show a
    hierarchy-scope flag for fsdbreport itself (only fsdb2vcd's sibling
    invocation in the same SKILL.md entry uses `-s <hier_scope>`) -- per
    the Tool Usage Verification Gate, an unconfirmed flag is never
    silently guessed onto a real command line.
    """
    from . import fsdb_report

    extra_args: List[str] = []
    if period:
        extra_args += ["-period", period]
    extra_args += ["-level", "1", "-csv"]

    run_result = fsdb_report.run_fsdbreport(fsdb_path, extra_args=extra_args)
    if not run_result.get("ok"):
        return {
            "ok": False,
            "error": run_result.get("error"),
            "detail": run_result.get("detail"),
            "returncode": run_result.get("returncode"),
            "stderr": run_result.get("stderr"),
            "hier_requested": hier,
            "parsed": False,
            "records": [],
        }

    parsed = fsdb_report.parse_fsdbreport_output(run_result["report_text"])
    return {"ok": True, "hier_requested": hier, **parsed}


def _ingest_coverage_summary_to_evidence_db(root: Path, timestamp: Any = None) -> int:
    """Lands this project's REAL current per-category coverage numbers as
    append-only `coverage_samples` rows in the DuckDB evidence store, so the
    cross-run daily coverage curve has something to be computed FROM
    (cross-run-trend task, 2026-09-03).

    THE GAP THIS CLOSES: `evidence_db.insert_coverage_sample()` and its
    append-only `coverage_samples` table were both real and unit-tested but
    had ZERO production call sites -- no real coverage run ever landed a row,
    so the table was permanently empty and every coverage trend query over it
    returned nothing. This is that call site.

    Reads `.dv-harness/coverage/summary.json` through
    `coverage_analysis.parse_coverage_summary()`, the SAME validated
    `{"name","percent","bins_total","bins_hit"}` shape GET /api/coverage
    already renders -- never a re-parse with different rules. Returns the
    number of category rows written (0 when there is no summary file yet, or
    when it is malformed, or when the evidence store is disabled/unavailable).

    Deliberately NOT invented when summary.json is absent: the aggregate
    `coverage_credit_percent` its caller has in hand carries no real
    bins_total/bins_hit, and fabricating those two columns to force a row in
    would put invented numbers into the evidence database. No summary file
    means no per-category evidence, and this honestly writes nothing -- the
    percent still reaches `history.json` through the caller either way."""
    try:
        from . import config as _config
        if not _config.load_config(root).get("evidence_db", {}).get("enabled", True):
            return 0
        s_path = _default_coverage_summary_path(root)
        if not s_path.exists():
            return 0
        from . import coverage_analysis as ca
        parsed = ca.parse_coverage_summary(json.loads(s_path.read_text(encoding="utf-8")))
        from . import evidence_db as _evidence_db
        written = 0
        with _evidence_db.EvidenceStore(_evidence_db.default_db_path(root)) as store:
            for category in parsed["categories"]:
                store.insert_coverage_sample(category, timestamp=timestamp,
                                              source=str(s_path))
                written += 1
        return written
    except Exception as e:
        # Same best-effort discipline every other evidence-store write in this
        # project uses (see regression_reporter._write_reconciliation_evidence_
        # if_configured): a duckdb-not-installed / locked-file / malformed-
        # summary problem must never break an already-earned COVERAGE_CLOSURE
        # PASS, nor the history.json append its caller performs regardless.
        print(f"[coverage] evidence store coverage sample write failed: {e}", flush=True)
        return 0


def append_coverage_history_sample(root: Path, percent: float, timestamp: Any = None) -> list:
    """Thin wrapper over coverage_analysis.append_history_sample(), pointed
    at this project's default .dv-harness/coverage/history.json -- the real
    production call a coverage-producing step makes to grow the history GET
    /api/coverage's trend/trend_svg fields read. Called by engine.py's
    DVHarness._append_coverage_history_sample() on every real
    COVERAGE_CLOSURE PASS (Task 6, 2026-08-31 poster-gap-closing round 2),
    with the percent taken from coverage_signoff_verdict_gate's own
    gate-verified coverage_credit_percent evidence field -- never a
    placeholder.

    Also mirrors this project's real per-category coverage summary into the
    DuckDB evidence store (cross-run-trend task, 2026-09-03) -- see
    `_ingest_coverage_summary_to_evidence_db()`. Wired HERE rather than at
    engine.py's call site so both the flat history.json trend chart and the
    cross-run daily coverage curve are fed by the same one real moment (a
    gate-verified COVERAGE_CLOSURE PASS), with no second call site an engine
    change could forget."""
    from . import coverage_analysis as ca
    history = ca.append_history_sample(_default_coverage_history_path(root), percent, timestamp)
    _ingest_coverage_summary_to_evidence_db(root, timestamp=timestamp)
    return history


def _blackboard_topics(root: Path):
    """Lists the REAL current .dv-harness/blackboard/*.json topic files
    (never a hardcoded list) -- used to honestly show that no dedicated
    'evidence' topic exists among them today, rather than fabricating a
    unified evidence store that isn't real."""
    bb_dir = root / ".dv-harness" / "blackboard"
    if not bb_dir.is_dir():
        return []
    return sorted(p.stem for p in bb_dir.glob("*.json"))


# --- Intake Uploads (.dv-harness/uploads/<category>/<filename>) ------------
# Poster-compliance audit (2026-08-29): the real Setup card had no file-upload
# mechanism for any of the 5 real evidence categories CLAUDE.md/
# intake_readiness.py care about. Implemented as base64-encoded content in a
# JSON POST body (POST /api/upload) -- matching every other POST endpoint in
# this file -- because Python's cgi module (the old multipart/form-data
# parser) is removed as of Python 3.13, and hand-rolling a multipart parser
# is out of scope for this feature.
_UPLOAD_CATEGORIES = ("spec", "rtl", "command_txt", "vip_reference", "de_sim")

# base64 inflates size by ~4/3 -- reject an oversized payload by inspecting
# the encoded string's length BEFORE calling base64.b64decode, so an
# oversized request never gets fully decoded into memory first.
_MAX_UPLOAD_DECODED_BYTES = 50 * 1024 * 1024
_MAX_UPLOAD_B64_CHARS = _MAX_UPLOAD_DECODED_BYTES * 4 / 3

_UPLOAD_FILENAME_CHARSET_RE = re.compile(r"[A-Za-z0-9\-_. ]+")


def _upload_root(root: Path) -> Path:
    return root / ".dv-harness" / "uploads"


def _validate_upload_filename(filename: str) -> None:
    """Rejects (never silently strips/replaces) a filename that is empty,
    tries to escape its directory ('/', '\\', or '..' anywhere), is hidden
    (leading '.'), or uses any character outside the safe charset -- a
    filename trying to escape its directory is a real attack attempt, not a
    formatting nit, and silently replacing disallowed characters would save
    a file under a name different from what the uploader thinks they sent."""
    if not filename:
        raise ValueError("filename must not be empty")
    if "/" in filename or "\\" in filename or ".." in filename:
        raise ValueError("filename must not contain '/', '\\', or '..'")
    if filename.startswith("."):
        raise ValueError("filename must not start with '.' (no hidden files)")
    if not _UPLOAD_FILENAME_CHARSET_RE.fullmatch(filename):
        raise ValueError("filename must only contain letters, digits, '-', '_', '.', and spaces")


def _unique_upload_filename(dir_path: Path, filename: str) -> str:
    """Never overwrites an existing file of the same name -- appends a
    numeric suffix before the extension (foo.v, foo_1.v, foo_2.v, ...) so two
    different uploads of the same filename never clobber each other."""
    if not (dir_path / filename).exists():
        return filename
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    i = 1
    while True:
        candidate = f"{stem}_{i}{suffix}"
        if not (dir_path / candidate).exists():
            return candidate
        i += 1


def _uploaded_files(root: Path) -> Dict[str, Any]:
    """Real files currently on disk under .dv-harness/uploads/<category>/,
    for GET /api/state's uploaded_files field -- a category with zero files
    reports an empty list (rendered by the frontend as "(none yet)"), never a
    fabricated placeholder entry."""
    base = _upload_root(root)
    out: Dict[str, Any] = {}
    for category in _UPLOAD_CATEGORIES:
        cat_dir = base / category
        files = []
        if cat_dir.is_dir():
            for p in sorted(cat_dir.iterdir()):
                if p.is_file():
                    files.append({"filename": p.name, "bytes": p.stat().st_size})
        out[category] = files
    return out


# --- Project setup metadata (.dv-harness/project_meta.json) ----------------
# Purely descriptive: the Linux DB/handoff path and this project's own
# working path, as the user wants them visible/recorded -- not something the
# harness itself interprets or acts on. GET /api/state surfaces this so the
# frontend can gate the Start controls on it (see the Waveform/SSH/Execution-
# Mode gates in CLAUDE.md -- this dashboard must not auto-start the harness
# before the user has actually configured the project here).
def _project_meta_path(root: Path) -> Path:
    return root / ".dv-harness" / "project_meta.json"


def _load_project_meta(root: Path) -> Dict[str, Any]:
    p = _project_meta_path(root)
    try:
        data = _read_json_file(p, default=None)
    except Exception:
        data = None
    if not isinstance(data, dict):
        return {"db_path": None, "working_path": None, "configured_at": None, "configured": False}
    db_path = data.get("db_path")
    working_path = data.get("working_path")
    return {
        "db_path": db_path,
        "working_path": working_path,
        "configured_at": data.get("configured_at"),
        "configured": bool(db_path and working_path),
    }


def _save_project_meta(root: Path, db_path: str, working_path: str) -> Dict[str, Any]:
    from .control_plane import now as cp_now
    p = _project_meta_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = {"db_path": db_path, "working_path": working_path, "configured_at": cp_now()}
    fd, tmp = tempfile.mkstemp(prefix="project_meta.", suffix=".json", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        _atomic_replace(tmp, p)  # see storage._atomic_replace's docstring
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return {**data, "configured": True}


def _default_signoff_export_dir(root: Path) -> Path:
    """Timestamped default so a POST /api/signoff-export with no out_dir
    never silently clobbers a previous export's manifest.json -- same
    time.strftime pattern session_snapshot.save_session() uses for its own
    default name."""
    return root / ".dv-harness" / "signoff-export" / time.strftime("%Y%m%d-%H%M%S")


# --- Background run launcher (POST /api/start) ------------------------------
# One in-flight run per project_root at a time, tracked by a module-level
# flag (this module -- and therefore this flag -- is per-process, matching
# ThreadingHTTPServer's single-process model; two independent `dv-harness
# dashboard` processes against the same project_root are not coordinated by
# this, same as two independent CLI invocations never were).
_active_runs: Dict[str, bool] = {}
_active_lock = threading.Lock()

# --- GUI Observability: this process's own real, self-measured route
# latency (Web Control Plane theme -- "a small Observability panel showing
# API route latency and the real events.jsonl backlog/staleness this
# dashboard process itself can measure about its own operation"). Per-route
# rolling window of wall-clock durations, recorded once per response inside
# Handler._send() below (every do_GET/do_POST branch ends up there, either
# directly or through _send_json) -- never a fabricated number, and never a
# claim about latency this SAME process has not actually observed. Module-
# level and per-process, matching `_active_runs`' own documented scope: two
# independent `dv-harness dashboard` processes are not coordinated by this.
_ROUTE_LATENCY_SAMPLES: Dict[str, List[float]] = {}
_ROUTE_LATENCY_LOCK = threading.Lock()
_ROUTE_LATENCY_MAX_SAMPLES = 100
_DASHBOARD_PROCESS_START = time.monotonic()


def _record_route_latency(route: str, elapsed_ms: float) -> None:
    with _ROUTE_LATENCY_LOCK:
        samples = _ROUTE_LATENCY_SAMPLES.setdefault(route, [])
        samples.append(elapsed_ms)
        if len(samples) > _ROUTE_LATENCY_MAX_SAMPLES:
            del samples[: len(samples) - _ROUTE_LATENCY_MAX_SAMPLES]


def _run_key(root: Path) -> str:
    return str(Path(root).resolve())


def _is_running(root: Path) -> bool:
    return _active_runs.get(_run_key(root), False)


def _start_background_run(root: Path, goal: str, loop: bool,
                           adapter_factory: Optional[Callable[[], Any]] = None,
                           protocols: Sequence[str] = (),
                           role: Optional[str] = None,
                           level: Optional[str] = None,
                           task_boundary: Optional[Any] = None,
                           generation_request: Optional[Dict[str, Any]] = None,
                           generation_out_dir: Optional[Path] = None) -> None:
    """Launches DVHarness(root).start_lifecycle(goal, loop=loop) on a
    background daemon thread so the HTTP request returns immediately.
    Raises RuntimeError('ALREADY_RUNNING') instead of starting a second
    concurrent run for the same project_root.

    CAP-M6-DISPATCH-001 (DEC-M6-DISPATCH-001, OPTION_A): converges on the
    same lifecycle-first entry point cli.py's `start` uses, rather than
    calling .loop()/.run_stage() directly -- start_lifecycle() itself still
    delegates to exactly those two methods once the lifecycle-first gate/
    field-resolution/task-boundary checks pass, so this is additive, not a
    new execution path.

    `protocols`/`role`/`level`/`task_boundary`/`generation_request`/
    `generation_out_dir` (M6 C1, CAP-M6-C1-001; `role` added by GAP-V2-002
    remediation; `level` wired by CAP-M5M6-VLEVEL-001; `task_boundary`
    wired by M6-TASK-BOUNDARY-PRODUCTION-001) are the dashboard's own
    additive counterpart to cli.py's `--protocols`/`--dut-role`/`--level`/
    `--task-boundary-*`/`--generate`/`--generate-out`/`--generate-manifest`
    flags -- all default to their pre-C1 empty/None values, so a caller
    that supplies none of them gets byte-identical behavior to before any
    of these closures. `task_boundary` is a real
    `task_boundary_conformance.TaskBoundary` (CAP-ATL-004, reused verbatim)
    or `None` -- `None` (the default) means start_lifecycle()'s own
    pre-existing Task Boundary check never runs, exactly as before this
    parameter existed.

    adapter_factory is a test-only seam: when given, the background
    thread's freshly-constructed DVHarness has its .adapter replaced with
    adapter_factory() before start_lifecycle() is called, so tests can
    inject a fake adapter without spawning a real `claude` CLI subprocess.
    Production callers (dv_harness.dashboard.serve() with no factory
    argument, i.e. `python -m dv_harness.dashboard`) leave this None and get
    the harness's normal adapter selection (dv_harness.engine.DVHarness._adapter).
    """
    key = _run_key(root)
    with _active_lock:
        if _active_runs.get(key):
            raise RuntimeError("ALREADY_RUNNING: a harness run is already in progress for this project")
        _active_runs[key] = True

    def _worker():
        try:
            from .engine import DVHarness
            h = DVHarness(root)
            if adapter_factory is not None:
                h.adapter = adapter_factory()
            # CAP-M6-DISPATCH-001 (DEC-M6-DISPATCH-001, OPTION_A -- approved):
            # dashboard's own launcher converges on the same lifecycle-first
            # entry point cli.py's "start" uses (item 2 of the approval),
            # instead of calling loop()/run_stage() directly.
            h.start_lifecycle(goal, loop=loop, protocols=protocols, role=role, level=level,
                              task_boundary=task_boundary,
                              generation_request=generation_request,
                              generation_out_dir=generation_out_dir)
        except Exception:
            # Background thread: an uncaught exception here has no HTTP
            # response to surface through (the POST /api/start request
            # already returned {"started": true}). run_stage()/loop() already
            # persist FAIL/PARTIAL/BLOCKED status + events.jsonl for the
            # ordinary failure paths; this is only for something that threw
            # before/outside that (e.g. DVHarness construction itself) --
            # print it rather than losing it silently.
            traceback.print_exc()
        finally:
            with _active_lock:
                _active_runs[key] = False

    threading.Thread(target=_worker, daemon=True).start()


# --- Change Impact View (GET /api/change-impact) -----------------------------
# Surfaces change_impact.py's own real, already-computed CHANGE -> DESIGN ->
# REQUIREMENT/VPLAN/PATTERN/COVERAGE impact analysis for the project's current
# diff -- exactly the payload `compute_and_write()` already wrote to
# `.dv-harness/regression/computed_selection.json` at REGRESSION_SELECT, never
# a second, dashboard-local re-derivation of risk/confidence/selection. This
# card computes nothing: it reads `read_computed_selection()` verbatim.
def _read_change_impact_state(root: Path) -> Dict[str, Any]:
    """A project that has never run REGRESSION_SELECT (or whose engine.py call
    site has not reached it yet) honestly reports `available: False` naming
    the real command that would populate it -- the same contract every other
    GET /api/... reader on this page already holds to. Read-only: this never
    runs `git diff` itself, never re-classifies a file's risk, and never
    recomputes a selection -- `read_computed_selection()` is documented as
    never raising, but this still degrades any unexpected failure honestly
    rather than surfacing a bare 500."""
    from . import change_impact
    try:
        payload = change_impact.read_computed_selection(root)
    except Exception as e:
        return {"available": False,
                "reason": f"COMPUTED_SELECTION_UNREADABLE: {type(e).__name__}: {e}"}
    if not payload:
        return {"available": False,
                "reason": "NO_COMPUTED_CHANGE_IMPACT (run REGRESSION_SELECT, or "
                          "`python -m dv_harness.change_impact`, to populate "
                          ".dv-harness/regression/computed_selection.json)"}
    return {"available": True, "payload": payload}


# --- Minimum Safe Regression View (GET /api/regression-tier) -----------------
# Surfaces regression_tiers.py's own real tiered-cadence policy table
# (SMOKE/NIGHTLY/WEEKLY: which selection classes, time budget,
# uvm_fatal_burst_threshold) plus, when a tier is currently declared active
# (.dv-harness/regression/active_tier.json) and a real change-impact selection
# has been computed, the real MINIMUM-SAFE test set that tier resolves via
# `tests_for_tier()` -- never a re-derived selection of its own.
def _read_regression_tier_state(root: Path) -> Dict[str, Any]:
    """A project with no active tier declared reports the real policy table
    alone and `active_tier: None`, honestly -- a flat, untiered project
    behaves exactly as regression_tiers.py itself documents (falls back to
    the flat pre-existing escalation threshold). config.json is read with the
    same plain, tolerant `_read_json_file()` every other card on this page
    already uses -- never `config.load_config()`, which would MINT a default
    config.json for a project asking only to view its regression tier."""
    from . import regression_tiers as _tiers
    from . import change_impact as _ci
    cfg = _read_json_file(root / ".dv-harness" / "config.json", default={}) or {}
    try:
        policies = {k: v.to_dict() for k, v in _tiers.all_policies(cfg).items()}
    except Exception as e:
        return {"available": False,
                "reason": f"REGRESSION_TIER_POLICY_UNAVAILABLE: {type(e).__name__}: {e}"}
    try:
        active = _tiers.read_active_tier(root)
    except Exception:
        active = None
    minimum_safe = None
    if active:
        try:
            selection_payload = _ci.read_computed_selection(root)
            selection = (selection_payload or {}).get("selection")
            universe = _ci.full_pattern_universe(root)
            minimum_safe = _tiers.tests_for_tier(
                active.get("tier"), selection, cfg=cfg,
                full_pattern_universe=universe)
        except Exception as e:
            minimum_safe = {"available": False,
                             "reason": f"MINIMUM_SAFE_REGRESSION_UNAVAILABLE: {type(e).__name__}: {e}"}
    return {"available": True, "policies": policies, "active_tier": active,
            "minimum_safe_regression": minimum_safe}


# --- Dependency / Supply-Chain Governance (GET /api/dependency-supply-chain) -
# dependency-supply-chain-no-dashboard-card: dependency_supply_chain.py (a
# real, already-wired `dv-harness supply-chain` CLI verb -- pinned-version
# enforcement, declared-vs-REALLY-INSTALLED resolution against this
# interpreter, and an offline-only vulnerability-advisory check that reports
# NOT_AVAILABLE rather than a fabricated clean result) had zero dashboard
# surface: no card anywhere showed this project's own dependency inventory or
# advisory findings. This is a thin front door onto that module's own real
# `analyze_supply_chain()` -- never a second, dashboard-local re-derivation of
# pin-status/resolution/advisory logic. Unlike the AMBA cards above, this
# module needs no caller-declared JSON artifact on disk first: it scans this
# project's own real pyproject.toml/requirements*.txt and (optionally) its
# real $DESIGNWARE_HOME VIP install tree live, on every request, exactly as
# `dv-harness supply-chain check` already does.
def _read_dependency_supply_chain_state(root: Path,
                                         designware_home: Optional[str] = None,
                                         include_vip: bool = True,
                                         policy_path: Optional[str] = None,
                                         advisory_db_path: Optional[str] = None
                                         ) -> Dict[str, Any]:
    """Read-only by design: `analyze_supply_chain()` only reads
    pyproject.toml/requirements*.txt, a project's own real
    `.dv-harness/supply_chain/policy.json` (or a caller-supplied override),
    an optional offline advisory database, and this interpreter's own real
    `importlib.metadata` -- it writes nothing and gates nothing. A real
    `SupplyChainError` (a malformed policy document) is surfaced as this
    endpoint's own named error rather than a bare 500; any other unexpected
    failure degrades the same honest way rather than crashing the route."""
    from .dependency_supply_chain import SupplyChainError, analyze_supply_chain
    try:
        report = analyze_supply_chain(
            root=root, designware_home=designware_home, include_vip=include_vip,
            policy_path=policy_path, advisory_db_path=advisory_db_path)
    except SupplyChainError as e:
        return {"available": True, "report": None,
                "error": {"reason": "SUPPLY_CHAIN_POLICY_ERROR", "detail": {"message": str(e)}}}
    except Exception as e:
        return {"available": True, "report": None,
                "error": {"reason": f"UNEXPECTED_ERROR: {type(e).__name__}", "detail": {"message": str(e)}}}
    return {"available": True, "report": report, "error": None}


# --- Scenario-Pattern <-> command.txt Correspondence (GET /api/scenario-
# pattern-command-txt-correspondence) -----------------------------------------
# scenario-pattern-command-txt-correspondence-unwired: scenario_pattern_
# command_txt_correspondence.py (the real, already-`dv-harness`-CLI-wired
# cross-reference of vip_capability_extraction.py's declared VIPScenarioPatternIR
# sequence-pattern classes against a project's real command.txt/pattern
# branch_b* usages -- CORRESPONDENCE_CONFIRMED/CORRESPONDENCE_NOT_FOUND per
# usage, USED_IN_COMMAND_TXT/NOT_USED_IN_COMMAND_TXT per declared pattern) had
# zero dashboard surface. This is a thin front door onto that module's own real
# `scenario_pattern_records_from_capability_report_dict()` +
# `analyze_scenario_pattern_command_txt_correspondence()` -- never a second VIP
# indexer, command.txt parser, or branch-ownership heuristic.
#
# Unlike the AMBA registry/graph cards above, this module has no fixed
# conventional on-disk location for EITHER of its two real inputs: a
# `vip_capability_extraction.json` document (that module's own `--out-dir` is
# always caller-chosen) and the project's real command.txt/pattern files (no
# harness-wide glob convention exists for these -- see gates.py's own
# "harness-globbed enumeration of every command.txt" comment, which is itself
# describing a caller-supplied list, not a fixed directory). So both are
# query-string overrides with NO guessed default, exactly like
# `_read_amba_path_explorer_state()`'s caller-picked (master, slave) pair one
# card above: a request naming neither input honestly reports NOT_AVAILABLE
# rather than fabricating a location to scan.
def _read_scenario_pattern_command_txt_correspondence_state(
        root: Path, capability_report_path: Optional[Path] = None,
        command_files: Optional[list] = None) -> Dict[str, Any]:
    """Read-only by design: this only ever reads the caller-named
    `vip_capability_extraction.json` document and the caller-named
    command.txt/pattern files -- it writes nothing (no `--out-dir` is ever
    passed through from the dashboard). A missing/unreadable capability
    report, or a real `ScenarioPatternCommandTxtCorrespondenceError` from the
    module itself (e.g. a VIPScenarioPatternIR record with no resolvable
    class_name), is surfaced as this endpoint's own named error rather than a
    bare 500 or a silently empty report."""
    from . import scenario_pattern_command_txt_correspondence as spc
    cmd_files = list(command_files or [])
    empty = {"available": False, "capability_report_path":
             str(capability_report_path) if capability_report_path else None,
             "command_files": cmd_files, "report": None, "error": None}
    if not capability_report_path:
        return empty
    path = Path(capability_report_path)
    if not path.exists():
        return empty
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return {**empty, "available": True,
                "error": {"reason": "MALFORMED_CAPABILITY_REPORT_FILE",
                          "detail": {"message": str(e)}}}
    records = spc.scenario_pattern_records_from_capability_report_dict(data)
    try:
        report = spc.analyze_scenario_pattern_command_txt_correspondence(records, cmd_files)
    except spc.ScenarioPatternCommandTxtCorrespondenceError as e:
        return {**empty, "available": True,
                "error": {"reason": "SCENARIO_PATTERN_CORRESPONDENCE_ERROR",
                          "detail": {"message": str(e)}}}
    return {"available": True, "capability_report_path": str(path),
            "command_files": cmd_files, "report": report.to_dict(), "error": None}


# --- Intake Events (GET /api/intake-events) -----------------------------------
# intake-events-no-dashboard-card: intake_events.py (the real, fixed 18-event
# INTAKE_* taxonomy over `.dv-harness/events.jsonl`, opt-in-emitted from real
# `verification_intake_contract.py`/`intake_state.py` transitions via
# `storage.StateStore.event()`, and already reachable as its own
# `python -m dv_harness.intake_events` verb) had zero dashboard presence -- no
# live event feed or timeline card surfaced these events. This is a thin front
# door onto that module's own real `read_intake_events()` -- never a second
# events.jsonl parser (that function itself reuses `loop_telemetry.
# read_events()`, the same shared reader `platform_health.py` already reuses)
# and never a re-derivation of the eighteen-name taxonomy.
def _read_intake_events_state(root: Path) -> Dict[str, Any]:
    """Read-only by design: `read_intake_events()` only reads
    `.dv-harness/events.jsonl` -- it writes nothing. Emission is opt-in on
    intake_events.py's own writers (`store: Any = None` on every emitter, per
    that module's own CLAUDE.md section), so a project on which no caller has
    ever passed a real `store=` honestly reports zero events here, never a
    fabricated feed."""
    from . import intake_events as _ie
    try:
        events, scan = _ie.read_intake_events(root)
    except Exception as e:
        return {"available": True, "events": None, "scan": None,
                "taxonomy": list(_ie.INTAKE_EVENTS),
                "error": {"reason": f"UNEXPECTED_ERROR: {type(e).__name__}",
                          "detail": {"message": str(e)}}}
    return {"available": True, "events": events, "scan": scan,
            "taxonomy": list(_ie.INTAKE_EVENTS), "error": None}


# --- Pattern Runtime State Machine (GET /api/pattern-runtime-state) ----------
# pattern-runtime-state-machine-no-dashboard-card: pattern_runtime_state_
# machine.py (a real, already-wired `dv-harness pattern-runtime-state` CLI
# verb -- the per-pattern CREATED->...->PASS/FAIL/TIMEOUT/BLOCKED/CANCELLED
# runtime state machine with legal-transition enforcement) had zero dashboard
# presence: no card anywhere showed a pattern's own current runtime state or
# its real legal-transition table. This is a thin front door onto that
# module's own real `execute_verb()` -- never a second, dashboard-local
# re-derivation of the state machine, its legal-transition table, or its
# JSON persistence format.
def _read_pattern_runtime_state_machine_state(root: Path) -> Dict[str, Any]:
    """Read-only by design: `execute_verb("list"/"states", ..., as_json=True)`
    only reads `.dv-harness/pattern_runtime/records.json` (via
    `load_records()`, which returns an empty dict -- never an error -- for a
    project that has never tracked any pattern's runtime state) and renders
    the module's own static `PatternRuntimeState`/`LEGAL_TRANSITIONS` table.
    Nothing here writes a record or advances a pattern's state."""
    from . import pattern_runtime_state_machine as _prs
    try:
        list_text, list_code = _prs.execute_verb("list", root=str(root), as_json=True)
        records = json.loads(list_text) if list_code in (0, 2) else None
        if list_code not in (0, 2):
            return {"available": True, "records": None, "states": None,
                     "error": {"reason": "PATTERN_RUNTIME_STATE_LIST_FAILED",
                               "detail": {"message": list_text}}}
        states_text, states_code = _prs.execute_verb("states", root=str(root), as_json=True)
        states = json.loads(states_text) if states_code == 0 else []
    except Exception as e:
        return {"available": True, "records": None, "states": None,
                "error": {"reason": f"UNEXPECTED_ERROR: {type(e).__name__}",
                          "detail": {"message": str(e)}}}
    return {"available": True, "records": records or [], "states": states, "error": None}


# --- Protocol Selector (GET /api/protocol-selector) --------------------------
# GUI-02 (CLAUDE_L5_VIP_UVM_INTERACTIVE_INTAKE.md's PROTOCOL SELECTOR
# requirement): the GUI must distinguish user-selected protocol, auto-detected
# protocol, evidence, confidence, and conflict/ambiguity, with the backend
# `protocol-router` remaining authoritative according to evidence and policy.
# protocol_router.py's own real resolve_protocol() already implements that
# router; nothing here re-derives its normalization/alias/tie-break logic.
def _default_protocol_selector_inputs_path(root: Path) -> Path:
    return root / ".dv-harness" / "protocol_selector" / "inputs.json"


def _read_protocol_selector_state(root: Path,
                                   inputs_path: Optional[Path] = None) -> Dict[str, Any]:
    """Reads a caller-declared evidence document at this project's own
    conventional `.dv-harness/protocol_selector/inputs.json` path (mirroring
    the `.dv-harness/multi_vip_cooperation/inputs.json` convention elsewhere in
    this file) -- protocol_router.py discovers no project fact itself, per its
    own FIELD_ORDER contract (`protocol_hint`/`failing_test_name`/
    `active_config`/`modified_files`/`subsystem_boundary`), so this reader
    never invents one either. No file on disk yet is the honest
    `{"available": False, ...}` empty state, never a fabricated protocol.

    `resolve_protocol()` is called THREE times over the same declared fields,
    never re-derived a second way: (1) over `protocol_hint` alone, normalizing
    whatever the user actually typed into a canonical protocol/display_name --
    the real "user-selected protocol"; (2) over every OTHER declared field
    (failing_test_name/active_config/modified_files/subsystem_boundary), which
    is what the evidence alone resolves to independent of what the user
    declared -- the real "auto-detected protocol"; (3) over every declared
    field together, the real, unmodified authoritative tie-break SKILL.md's
    own order specifies (user intent first) -- this is protocol-router's own
    real answer, never a dashboard-local override of it. A genuine
    disagreement between (1) and (2) is reported as `conflict: True` and is
    never arbitrated here -- (3) already IS protocol-router's own
    authoritative answer to that disagreement; this card only surfaces it.

    `confidence` is this card's own presentation-only label (HIGH/MEDIUM/LOW/
    UNKNOWN), derived purely from whether (1) and (2) resolved and whether
    they agree -- protocol_router.py itself carries no confidence concept, so
    this label is never presented as if it were that module's own output."""
    from . import protocol_router as _pr

    path = Path(inputs_path) if inputs_path else _default_protocol_selector_inputs_path(root)
    empty = {"available": False, "inputs_path": str(path), "declared": None,
             "user_declared": None, "auto_detected": None, "authoritative": None,
             "conflict": None, "confidence": None, "error": None}
    if not path.exists():
        return empty

    try:
        declared = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return {**empty, "available": True,
                "error": {"reason": "MALFORMED_PROTOCOL_SELECTOR_INPUTS_FILE",
                          "detail": {"message": str(e)}}}
    if not isinstance(declared, dict):
        return {**empty, "available": True,
                "error": {"reason": "PROTOCOL_SELECTOR_INPUTS_NOT_A_DOCUMENT",
                          "detail": {"message": "top-level JSON must be an object"}}}

    try:
        full_evidence = {k: declared.get(k) for k in _pr.FIELD_ORDER}
        auto_evidence = {k: v for k, v in full_evidence.items() if k != "protocol_hint"}
        user_raw = declared.get("protocol_hint")
        user_declared = _pr.resolve_protocol({"protocol_hint": user_raw}) if user_raw else None
        auto_detected = _pr.resolve_protocol(auto_evidence)
        authoritative = _pr.resolve_protocol(full_evidence)
    except Exception as e:
        return {**empty, "available": True,
                "error": {"reason": f"UNEXPECTED_ERROR: {type(e).__name__}",
                          "detail": {"message": str(e)}}}

    user_protocol = user_declared.get("protocol") if user_declared else None
    auto_protocol = auto_detected.get("protocol") if auto_detected else None
    conflict = bool(user_protocol and auto_protocol and user_protocol != auto_protocol)
    if conflict:
        confidence = "LOW"
    elif user_protocol and auto_protocol and user_protocol == auto_protocol:
        confidence = "HIGH"
    elif user_protocol or auto_protocol:
        confidence = "MEDIUM"
    else:
        confidence = "UNKNOWN"

    return {
        "available": True,
        "inputs_path": str(path),
        "declared": full_evidence,
        "user_declared": user_declared,
        "auto_detected": auto_detected,
        "authoritative": authoritative,
        "conflict": conflict,
        "confidence": confidence,
        "error": None,
    }


# --- Intake Baseline (GET /api/intake-baseline) ------------------------------
# intake_baseline.py's own real per-project freeze/list/status card. Reuses
# ONLY that module's own real, unmodified functions: list_intake_freezes()
# (real, safe, zero-arg -- always called) and evaluate_all_intake_freezes()
# (needs real CURRENT facts to compare a freeze against; called ONLY when a
# real facts JSON file is found on disk at this project's own conventional
# path, .dv-harness/intake/current_facts.json, or supplied via an explicit
# `?current_facts=<path>` query param -- NEVER invoked with synthetic/None
# facts and rendered as a real VALID/INVALIDATED verdict, since that would
# misreport "everything invalidated" as a genuine finding). Never freezes,
# writes, or gates anything itself -- see intake_baseline.py's own module
# docstring ("REACHED, not WIRED... this module only reads already-frozen
# JSON off disk and re-derives a report").
def _default_current_facts_path(root: Path) -> Path:
    return Path(root) / ".dv-harness" / "intake" / "current_facts.json"


def _read_intake_baseline_state(root: Path,
                                 current_facts_path: Optional[Path] = None
                                 ) -> Dict[str, Any]:
    """Read-only by design: `list_intake_freezes()` only reads
    `.dv-harness/intake/baselines/*.json`, and `evaluate_all_intake_freezes()`
    is only ever called over a REAL, on-disk current-facts document -- never
    a fabricated/None one presented as a real evaluation."""
    from . import intake_baseline as _ib

    try:
        freezes = _ib.list_intake_freezes(root)
    except Exception as e:
        return {"available": True, "freezes": None, "evaluation": None,
                "current_facts_path": None,
                "error": {"reason": f"UNEXPECTED_ERROR: {type(e).__name__}",
                          "detail": {"message": str(e)}}}

    facts_path = current_facts_path or _default_current_facts_path(root)
    evaluation: Optional[Dict[str, Any]] = None
    evaluation_error: Optional[Dict[str, Any]] = None
    if facts_path.is_file():
        try:
            current_facts = json.loads(facts_path.read_text(encoding="utf-8"))
            if not isinstance(current_facts, dict):
                evaluation_error = {
                    "reason": "CURRENT_FACTS_FILE_MUST_BE_A_JSON_OBJECT",
                    "detail": {"path": str(facts_path)}}
            else:
                evaluation = _ib.evaluate_all_intake_freezes(root, current_facts)
        except (OSError, ValueError) as e:
            evaluation_error = {"reason": f"CURRENT_FACTS_FILE_UNREADABLE: {type(e).__name__}",
                                 "detail": {"path": str(facts_path), "message": str(e)}}
        except Exception as e:
            evaluation_error = {"reason": f"UNEXPECTED_ERROR: {type(e).__name__}",
                                 "detail": {"message": str(e)}}

    return {
        "available": True,
        "fields": list(_ib.INTAKE_FIELDS),
        "freezes": freezes,
        "current_facts_path": str(facts_path),
        "current_facts_supplied": facts_path.is_file(),
        "evaluation": evaluation,
        "error": evaluation_error,
    }


# --- Pattern Coverage Contribution (GET /api/pattern-coverage-contribution) --
# pattern_coverage_contribution.py's real per-pattern marginal coverage
# contribution (new bins hit, new meaningful cross bins hit, a bins-weighted
# coverage_delta_percent) plus real runtime/failure evidence from
# evidence_db.py's `jobs` table -- never a dashboard-local re-derivation of
# any of that arithmetic. `db_path` resolves via THIS project's own existing
# `_evidence_db.default_db_path(root)` convention (already used elsewhere in
# this file, e.g. `_ingest_coverage_summary_to_evidence_db()` above).
# `pattern` and the `sample_attribution`/`cross_definitions` JSON file paths
# come from query params, mirroring the FSDB-report arm's own "accept a
# declared path via query string" convention (`?path=`/`?period=`/`?hier=`
# above). `sample_attribution` is a REQUIRED, explicit, caller-declared fact
# this codebase has no producer for (per pattern_coverage_contribution.py's
# own module docstring) -- when no attribution file is supplied, this route
# returns an honest "not available, attribution required" payload, NEVER an
# invented one.
def _read_pattern_coverage_contribution_state(
        root: Path, pattern: Optional[str],
        attribution_path: Optional[Path] = None,
        cross_definitions_path: Optional[Path] = None) -> Dict[str, Any]:
    """Read-only: `compute_pattern_coverage_contribution()` opens
    `evidence.duckdb` `read_only=True` and writes nothing. Never invokes the
    real computation with a fabricated/empty `sample_attribution` -- that is
    the one fact this module cannot supply on its own, so its absence is
    reported honestly rather than silently substituted."""
    from . import pattern_coverage_contribution as _pcc
    from . import evidence_db as _evidence_db

    if not pattern:
        return {"available": False, "report": None,
                "error": {"reason": "PATTERN_QUERY_PARAM_REQUIRED",
                          "detail": {"message": "supply ?pattern=<name>"}}}

    db_path = _evidence_db.default_db_path(root)
    if not Path(db_path).exists():
        return {"available": False, "report": None,
                "error": {"reason": "EVIDENCE_DB_NOT_FOUND",
                          "detail": {"db_path": str(db_path)}}}

    if attribution_path is None:
        return {"available": False, "report": None,
                "error": {"reason": "SAMPLE_ATTRIBUTION_REQUIRED",
                          "detail": {"message":
                              "sample_attribution is required and this codebase has no "
                              "producer for it (per pattern_coverage_contribution.py's own "
                              "module docstring) -- supply ?attribution=<path to a JSON "
                              "file of [{\"source\": ..., \"pattern\": ...}, ...]>"}}}
    try:
        attribution = json.loads(Path(attribution_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return {"available": False, "report": None,
                "error": {"reason": f"ATTRIBUTION_FILE_UNREADABLE: {type(e).__name__}",
                          "detail": {"path": str(attribution_path), "message": str(e)}}}

    cross_definitions = None
    if cross_definitions_path is not None:
        try:
            cross_definitions = json.loads(Path(cross_definitions_path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            return {"available": False, "report": None,
                    "error": {"reason": f"CROSS_DEFINITIONS_FILE_UNREADABLE: {type(e).__name__}",
                              "detail": {"path": str(cross_definitions_path), "message": str(e)}}}

    try:
        report = _pcc.compute_pattern_coverage_contribution(
            db_path, pattern, attribution, cross_definitions=cross_definitions)
    except _pcc.PatternCoverageContributionError as e:
        return {"available": False, "report": None,
                "error": {"reason": "PATTERN_COVERAGE_CONTRIBUTION_INVALID_INPUT",
                          "detail": {"message": str(e)}}}
    except Exception as e:
        return {"available": False, "report": None,
                "error": {"reason": f"UNEXPECTED_ERROR: {type(e).__name__}",
                          "detail": {"message": str(e)}}}

    return {"available": True, "report": report, "error": None}


# --- Build/Remote/LSF Intake (GET /api/build-remote-lsf-intake) --------------
# build_remote_lsf_intake.py's own real build/remote/LSF readiness card --
# eda_license_available/lsf_configured/build_environment_reachable/
# disk_space_sufficient/workdir_ready/eda_env_vars_configured/
# remote_transport_available, each mapped from a real preflight.py
# CheckOutcome/TransportDecision.
#
# CRITICAL SAFETY CONSTRAINT (the one candidate in this family with real
# live-probe risk): preflight.run_preflight() performs real network/host/
# license/LSF-queue probes -- exactly the class of "real live LSF farm"
# check this environment forbids fabricating OR silently invoking on every
# dashboard page load. This route therefore NEVER calls
# preflight.run_preflight()/resolve_transport() itself. It follows the exact
# convention _read_resource_orchestrator_state() already established above:
# read an already-declared PreflightResult/TransportDecision-shaped JSON
# document off disk (a project-owned path, .dv-harness/build_remote_lsf_
# intake/preflight_result.json, written by whatever process already ran the
# REAL preflight.run_preflight() elsewhere, outside this request path),
# reconstruct real preflight.CheckOutcome/TransportDecision objects from it,
# and pass those into build_remote_lsf_intake.py's own real
# fields_from_preflight()/evaluate_build_remote_lsf_readiness() -- never a
# second, dashboard-local mapping of check status onto field status. Absent
# file -> honest "not available", mirroring resource_orchestrator's own
# empty return when its inputs file is missing.
def _default_build_remote_lsf_intake_inputs_path(root: Path) -> Path:
    return root / ".dv-harness" / "build_remote_lsf_intake" / "preflight_result.json"


def _read_build_remote_lsf_intake_state(root: Path,
                                         inputs_path: Optional[Path] = None) -> Dict[str, Any]:
    """Read-only by design, and NEVER live: this function performs zero
    subprocess calls and zero network I/O of its own -- it only reads a
    JSON file (written by a real preflight run elsewhere) and calls
    build_remote_lsf_intake.py's own real, unmodified field-mapping
    functions on the reconstructed objects."""
    from . import build_remote_lsf_intake as _brl
    from . import preflight as _preflight

    path = Path(inputs_path) if inputs_path else _default_build_remote_lsf_intake_inputs_path(root)
    empty = {"available": False, "inputs_path": str(path), "fields": None,
             "readiness": None, "error": None}
    if not path.exists():
        return empty

    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return {**empty, "available": True,
                "error": {"reason": "MALFORMED_INPUTS_FILE", "detail": {"message": str(e)}}}
    if not isinstance(doc, dict):
        return {**empty, "available": True,
                "error": {"reason": "INPUTS_NOT_AN_OBJECT", "detail": {}}}

    # preflight_result may be passed straight through as a plain dict --
    # build_remote_lsf_intake.fields_from_preflight()'s own real
    # _checks_by_name() normalizer already accepts a dict shaped like
    # preflight.PreflightResult.to_dict() (never re-derived here).
    preflight_result = doc.get("preflight_result")
    if preflight_result is not None and not isinstance(preflight_result, dict):
        return {**empty, "available": True,
                "error": {"reason": "PREFLIGHT_RESULT_NOT_AN_OBJECT", "detail": {}}}

    # transport_decision, unlike preflight_result, must become a REAL
    # preflight.TransportDecision object -- _field_from_transport_decision()
    # reads it via attribute access (decision.resolved/.evidence/.available/
    # .reason), not dict keys.
    transport_doc = doc.get("transport_decision")
    transport_decision = None
    if transport_doc is not None:
        if not isinstance(transport_doc, dict) or not transport_doc.get("requested") \
                or not transport_doc.get("resolved"):
            return {**empty, "available": True,
                    "error": {"reason": "TRANSPORT_DECISION_MALFORMED", "detail": {}}}
        transport_decision = _preflight.TransportDecision(
            requested=str(transport_doc["requested"]),
            resolved=str(transport_doc["resolved"]),
            available=bool(transport_doc.get("available", False)),
            reason=str(transport_doc.get("reason") or ""),
            evidence=transport_doc.get("evidence") or {},
        )

    try:
        fields = _brl.fields_from_preflight(preflight_result, transport_decision)
        readiness = _brl.evaluate_build_remote_lsf_readiness(fields)
    except Exception as e:
        return {**empty, "available": True,
                "error": {"reason": f"UNEXPECTED_ERROR: {type(e).__name__}",
                          "detail": {"message": str(e)}}}

    return {
        "available": True,
        "inputs_path": str(path),
        "fields": [f.to_dict() for f in fields],
        "readiness": readiness.to_dict(),
        "error": None,
    }


# --- Orphaned/Leaked-Fork Detection (GET /api/orphaned-fork-detection) ------
# GUI card surfacing orphaned_fork_detection.py's real branch_b*-internal
# non-blocking-VIP-sequence-dispatch/wait pairing check -- following the
# exact same fetch-real-artifact-and-render convention
# _read_evidence_integrity_signoff_blocker_state()/_read_design_knowledge_
# state() above already established, rather than inventing a new one.
#
# orphaned_fork_detection.py discovers no project fact itself: it needs a
# real pattern_dir to scan, and has no project-discovery path of its own for
# one. Absent a caller-declared
# .dv-harness/orphaned_fork_detection/inputs.json ({"pattern_dir": "...",
# "glob"?: "*.txt"}), the honest empty state is reported -- never a
# fabricated pattern_dir. analyze_pattern_directory() itself never raises on
# a missing/empty directory (Path.glob() on a nonexistent dir yields nothing
# -> FILE_NOT_APPLICABLE), so once a pattern_dir is declared this reader's
# own try/except is defense-in-depth only.
def _default_orphaned_fork_detection_inputs_path(root: Path) -> Path:
    return root / ".dv-harness" / "orphaned_fork_detection" / "inputs.json"


def _read_orphaned_fork_detection_state(root: Path,
                                         inputs_path: Optional[Path] = None) -> Dict[str, Any]:
    """orphaned_fork_detection.analyze_pattern_directory()'s real report for
    GET /api/orphaned-fork-detection, over a caller-declared pattern_dir --
    see the module comment above."""
    ip = Path(inputs_path) if inputs_path else _default_orphaned_fork_detection_inputs_path(root)
    empty = {"available": False, "inputs_path": str(ip), "report": None, "error": None}
    if not ip.exists():
        return empty

    try:
        inputs = json.loads(ip.read_text(encoding="utf-8"))
    except Exception as e:
        return {**empty, "available": True,
                "error": {"reason": "MALFORMED_INPUTS_FILE", "detail": {"message": str(e)}}}

    pattern_dir = inputs.get("pattern_dir") if isinstance(inputs, dict) else None
    if not pattern_dir:
        return {**empty, "available": True,
                "error": {"reason": "PATTERN_DIR_NOT_DECLARED", "detail": {}}}
    glob = inputs.get("glob") or "*.txt"

    from . import orphaned_fork_detection as ofd
    try:
        report = ofd.analyze_pattern_directory(pattern_dir, glob=glob)
    except Exception as e:
        return {**empty, "available": True,
                "error": {"reason": "ORPHANED_FORK_DETECTION_FAILED",
                          "detail": {"message": str(e)}}}

    return {"available": True, "inputs_path": str(ip), "report": report, "error": None}


# --- Multi-VIP Cooperation Architecting (GET /api/multi-vip-cooperation) ----
# GUI card surfacing multi_vip_cooperation_architecting.py's real per-
# interface-pair cooperation/architecture/sequencing report -- following the
# exact same fetch-real-artifact-and-render convention above.
#
# multi_vip_cooperation_architecting.py's own docstring is explicit that
# every fact (interfaces, coupling, sequencing) must be caller-declared -- it
# has no project-discovery path of its own. Absent a caller-declared
# .dv-harness/multi_vip_cooperation/inputs.json (interfaces/env_manifest/
# rtl_modules/declared_coupling_facts/sequencing_relations/
# sequencing_observations, exactly build_multi_vip_cooperation()'s own
# kwargs), the honest empty state is reported -- never a fabricated
# cooperation record, and this reader never auto-populates `interfaces` from
# env.manifest.json's own vip_config.vip_instances (a different fact --
# VIP instances already bound -- from what this module needs: declared
# candidate interfaces, including unbound ones).
def _default_multi_vip_cooperation_inputs_path(root: Path) -> Path:
    return root / ".dv-harness" / "multi_vip_cooperation" / "inputs.json"


def _read_multi_vip_cooperation_state(root: Path,
                                       inputs_path: Optional[Path] = None) -> Dict[str, Any]:
    """multi_vip_cooperation_architecting.build_multi_vip_cooperation()'s
    real report for GET /api/multi-vip-cooperation, over a caller-declared
    interface/coupling/sequencing set -- see the module comment above."""
    ip = Path(inputs_path) if inputs_path else _default_multi_vip_cooperation_inputs_path(root)
    empty = {"available": False, "inputs_path": str(ip), "report": None, "error": None}
    if not ip.exists():
        return empty

    try:
        inputs = json.loads(ip.read_text(encoding="utf-8"))
    except Exception as e:
        return {**empty, "available": True,
                "error": {"reason": "MALFORMED_INPUTS_FILE", "detail": {"message": str(e)}}}

    interfaces = inputs.get("interfaces") if isinstance(inputs, dict) else None
    if not interfaces:
        return {**empty, "available": True,
                "error": {"reason": "INTERFACES_NOT_DECLARED", "detail": {}}}

    from . import multi_vip_cooperation_architecting as mvca
    try:
        ir = mvca.build_multi_vip_cooperation(
            interfaces,
            env_manifest=inputs.get("env_manifest"),
            rtl_modules=inputs.get("rtl_modules"),
            declared_coupling_facts=inputs.get("declared_coupling_facts"),
            sequencing_relations=inputs.get("sequencing_relations"),
            sequencing_observations=inputs.get("sequencing_observations"),
        )
    except mvca.MultiVipCooperationError as e:
        return {**empty, "available": True,
                "error": {"reason": "MULTI_VIP_COOPERATION_INVALID_INPUT",
                          "detail": {"message": str(e)}}}
    except Exception as e:
        return {**empty, "available": True,
                "error": {"reason": "MULTI_VIP_COOPERATION_FAILED",
                          "detail": {"message": str(e)}}}

    return {"available": True, "inputs_path": str(ip), "report": ir.to_dict(), "error": None}


# --- DUT Errata/Known-Issues Correlation (GET /api/dut-errata-correlation) --
# GUI card surfacing dut_errata_correlation.py's real per-erratum RTL/
# register correlation report -- following the exact same fetch-real-
# artifact-and-render convention above.
#
# dut_errata_correlation.analyze_errata()'s own contract already returns the
# honest top-level NOT_AVAILABLE for a source_path of None without ever
# attempting to open anything, so this reader calls it UNCONDITIONALLY -- no
# special-casing for a missing inputs.json is needed here (unlike the two
# readers above, whose underlying build functions raise on no real facts at
# all). `source_path` has no project-discovery path of its own (no errata
# PDF is auto-produced by anything in this repo), so it is read from a
# caller-declared .dv-harness/dut_errata_correlation/inputs.json
# ({"source_path": "...", "title"?: "..."}); `manifest_path` reuses the
# already-established env_manifest.default_manifest_path(root) helper -- the
# exact same call dashboard.py's own subsystem_system_verification reader
# already makes. analyze_errata() never raises by design (it catches
# ErrataDocumentError internally and returns a NOT_AVAILABLE dict); the
# try/except below is defense-in-depth only.
def _default_dut_errata_correlation_inputs_path(root: Path) -> Path:
    return root / ".dv-harness" / "dut_errata_correlation" / "inputs.json"


def _read_dut_errata_correlation_state(root: Path,
                                        inputs_path: Optional[Path] = None) -> Dict[str, Any]:
    """dut_errata_correlation.analyze_errata()'s real report for
    GET /api/dut-errata-correlation -- see the module comment above."""
    ip = Path(inputs_path) if inputs_path else _default_dut_errata_correlation_inputs_path(root)
    source_path = None
    title = None
    malformed_inputs_error = None
    if ip.exists():
        try:
            inputs = json.loads(ip.read_text(encoding="utf-8"))
            if isinstance(inputs, dict):
                source_path = inputs.get("source_path")
                title = inputs.get("title")
        except Exception as e:
            malformed_inputs_error = {"reason": "MALFORMED_INPUTS_FILE",
                                       "detail": {"message": str(e)}}

    from . import env_manifest
    manifest_path = env_manifest.default_manifest_path(root)

    from . import dut_errata_correlation as dec
    try:
        report = dec.analyze_errata(source_path, manifest_path, title=title)
    except Exception as e:
        return {"available": True, "inputs_path": str(ip), "report": None,
                "error": {"reason": "DUT_ERRATA_CORRELATION_FAILED",
                          "detail": {"message": str(e)}}}

    return {"available": True, "inputs_path": str(ip), "report": report,
            "error": malformed_inputs_error}


# --- Memory Quality Policy (GET /api/memory-quality-policy) ------------------
# memory-quality-policy-no-dashboard-card: memory_quality_policy.py (a real,
# already-wired `dv-harness memory-quality-policy report|apply` CLI verb --
# the age/never-confirmed/duplicate retirement DECISION layer over the
# existing, unmodified `MemoryGC` mechanism) had zero dashboard surface: no
# card anywhere showed which memory records this project's own real policy
# would flag stale, deprecate, or supersede. This is a thin front door onto
# that module's own real `evaluate_memory_quality()` -- never a second,
# dashboard-local re-derivation of the age/never-confirmed/duplicate
# thresholds or the FLAG_STALE/DEPRECATE/SUPERSEDE decision logic. It always
# calls the READ-ONLY report half (never `apply_memory_quality_policy()`) --
# this route can never retire a memory record; it only renders what a human
# would see before choosing to run `dv-harness memory-quality-policy apply`
# themselves.
def _read_memory_quality_policy_state(root: Path) -> Dict[str, Any]:
    """Read-only by design: `evaluate_memory_quality()` checks
    `cross_project_mining.has_memory_store()` before ever constructing a
    `MemoryStore` (whose constructor would `mkdir()` the 5-tier tree), so a
    project with no memory store yet is honestly reported `NOT_AVAILABLE`
    rather than gaining one merely from a dashboard page load."""
    from .memory_quality_policy import evaluate_memory_quality
    try:
        report = evaluate_memory_quality(root)
    except Exception as e:
        return {"available": True, "report": None,
                "error": {"reason": f"UNEXPECTED_ERROR: {type(e).__name__}",
                          "detail": {"message": str(e)}}}
    return {"available": True, "report": report, "error": None}


# --- Notification Center (GET /api/notifications) ----------------------------
# Two real, already-computed facts -- never a new alerting engine: (1)
# escalation_notify.py's own escalation CONFIGURATION (enabled / apprise_urls
# configured / uvm_fatal_burst_threshold) -- no transport is ever constructed
# here, so this never attempts a live network send; (2) harness_status.py's
# own persisted HARNESS_STATUS_SNAPSHOT history, filtered to entries whose own
# real `transitioned` field is True -- the literal change-only-notification
# record `HarnessStatusService.publish()` already produces (that function
# fires escalation_notify.EscalationNotifier.signoff_blocked() only on
# exactly such a transition -- see harness_status.py's own module docstring).
def _read_notification_center_state(root: Path) -> Dict[str, Any]:
    """A project with no recorded HARNESS_STATUS_SNAPSHOT history honestly
    reports an empty `notifications` list (never a fabricated one) naming the
    real command (`dv-harness status --record`) that would populate it -- the
    literal 'never re-notify on an unchanged state' discipline is what the
    real `transitioned` field already encodes; this card only filters on it,
    it never recomputes it."""
    from . import escalation_notify as _esc
    from . import regression_tiers as _tiers
    cfg = _read_json_file(root / ".dv-harness" / "config.json", default={}) or {}
    try:
        econf = _esc.config_from_dict(cfg.get("escalation"))
        escalation_config = {
            "enabled": econf.enabled,
            "transport_configured": bool(econf.enabled and econf.apprise_urls),
            "apprise_url_count": len(econf.apprise_urls),
            "uvm_fatal_burst_threshold_default": econf.uvm_fatal_burst_threshold,
        }
    except Exception as e:
        escalation_config = {"available": False,
                              "reason": f"ESCALATION_CONFIG_UNAVAILABLE: {type(e).__name__}: {e}"}
    try:
        active_threshold = _tiers.active_uvm_fatal_burst_threshold(root, cfg)
    except Exception:
        active_threshold = None
    notifications: List[Dict[str, Any]] = []
    history_available = False
    reason = None
    try:
        from . import harness_status as _hs
        hist = _hs.read_harness_status_history(root)
    except Exception as e:
        hist = {"available": False, "reason": f"HARNESS_STATUS_HISTORY_UNREADABLE: {type(e).__name__}: {e}"}
    if hist.get("available"):
        history_available = True
        for entry in (hist.get("history") or []):
            if entry.get("transitioned"):
                notifications.append({
                    "ts": entry.get("ts"),
                    "previous_state": entry.get("previous_state"),
                    "harness_state": entry.get("harness_state"),
                    "signoff_state": entry.get("signoff_state"),
                    "trigger": entry.get("trigger"),
                    "user_agent_action": entry.get("user_agent_action"),
                })
    else:
        reason = hist.get("reason") or "NO_HARNESS_STATUS_HISTORY_RECORDED"
    return {
        "available": True,
        "escalation_config": escalation_config,
        "active_uvm_fatal_burst_threshold": active_threshold,
        "history_available": history_available,
        "notifications": notifications,
        "notifications_reason": reason,
    }


def _event_ts_to_epoch(ts: Any) -> Optional[float]:
    """events.jsonl carries a genuine MIX of writers: some stamp `time.time()`
    (a numeric epoch), others `engine.now()` (an ISO-8601 string with a real
    UTC offset). Both are handled honestly here rather than assuming one
    shape; anything this cannot parse degrades to None rather than a
    fabricated staleness figure."""
    if isinstance(ts, (int, float)) and not isinstance(ts, bool):
        return float(ts)
    if isinstance(ts, str):
        try:
            from datetime import datetime
            s = ts[:-1] + "+00:00" if ts.endswith("Z") else ts
            return datetime.fromisoformat(s).timestamp()
        except Exception:
            return None
    return None


# --- GUI Observability panel (GET /api/observability) ------------------------
# Two facts THIS dashboard process can honestly measure about its own
# operation: (1) API route latency -- the last N wall-clock durations this
# same process measured for its own served routes (module-level
# `_ROUTE_LATENCY_SAMPLES`, recorded once per response inside `Handler._send()`
# below); empty for a route/process that has never served one, never a
# fabricated number. (2) the real `.dv-harness/events.jsonl` backlog/staleness
# -- reused from `loop_telemetry.read_events()` (the one real trailing-window
# parser this project already has for that file), never a second parser.
def _read_gui_observability_state(root: Path) -> Dict[str, Any]:
    from . import loop_telemetry
    routes: List[Dict[str, Any]] = []
    with _ROUTE_LATENCY_LOCK:
        snapshot_samples = {k: list(v) for k, v in _ROUTE_LATENCY_SAMPLES.items()}
    for route in sorted(snapshot_samples):
        samples = snapshot_samples[route]
        if not samples:
            continue
        ordered = sorted(samples)
        n = len(ordered)
        routes.append({
            "route": route,
            "sample_count": n,
            "last_ms": round(samples[-1], 2),
            "avg_ms": round(sum(samples) / n, 2),
            "p50_ms": round(ordered[n // 2], 2),
            "max_ms": round(ordered[-1], 2),
        })
    try:
        entries, lines_scanned, truncated = loop_telemetry.read_events(root)
    except Exception as e:
        events_backlog: Dict[str, Any] = {
            "available": False, "reason": f"EVENTS_JSONL_UNREADABLE: {type(e).__name__}: {e}"}
    else:
        events_file = Path(root) / ".dv-harness" / "events.jsonl"
        if lines_scanned == 0:
            events_backlog = {
                "available": False,
                "reason": ("NO_EVENTS_JSONL_YET" if not events_file.exists()
                           else "EVENTS_JSONL_EMPTY"),
                "total_lines": 0,
            }
        else:
            last_ts = None
            for e in reversed(entries):
                if e.get("ts") is not None:
                    last_ts = e.get("ts")
                    break
            epoch = _event_ts_to_epoch(last_ts)
            staleness_seconds = max(0.0, time.time() - epoch) if epoch is not None else None
            events_backlog = {
                "available": True,
                "total_lines": lines_scanned,
                "scan_truncated": truncated,
                "last_event_ts": last_ts,
                "staleness_seconds": (round(staleness_seconds, 1)
                                      if staleness_seconds is not None else None),
            }
    return {"available": True, "routes": routes, "events_backlog": events_backlog,
            "process_uptime_seconds": round(time.monotonic() - _DASHBOARD_PROCESS_START, 1)}


# --- GET /api/events/stream: Server-Sent-Events push transport for
# live_event_model.py's own eleven-name GUI_* vocabulary (Web Control Plane
# theme, sections 342-402). That module's own docstring is explicit about
# what it deliberately does NOT do: "the actual push-to-browser transport
# (a WebSocket/SSE server, a browser-side subscriber) is a separate, later
# item and is deliberately not built here." This is that later item, and
# only that -- it adds no second events.jsonl parser and computes no new
# fact: `_new_gui_live_events()` below is a thin poll wrapper around
# live_event_model.list_gui_live_events(), the one real reader that module
# already ships, tested. The actual chunked write loop lives inline in
# do_GET (it needs this connection's own live socket), built on the plain
# stdlib http.server machinery every other route in this file already uses
# -- no new dependency, per this item's own scope.
def _new_gui_live_events(root: Path, since_ts: str, since_ts_seen: int
                         ) -> "tuple[List[Dict[str, Any]], str, int]":
    """One poll cycle: the events live_event_model.list_gui_live_events()
    reports as of right now, narrowed to whatever this one SSE connection
    has not already sent.

    since_ts/since_ts_seen are this connection's own watermark, carried by
    the caller across polls. live_event_model.list_gui_live_events()'s own
    `since_ts` bound is INCLUSIVE (string-compared ISO-8601, per its own
    docstring) -- so two poll cycles a moment apart can both legally include
    the SAME boundary event. since_ts_seen (how many events already sent
    share that exact `ts`) is what lets this function tell "already sent"
    apart from "genuinely new" among same-`ts` events, rather than either
    dropping or re-sending them. Returns (new_events, updated_since_ts,
    updated_since_ts_seen); new_events is oldest-first, unchanged from
    list_gui_live_events()'s own documented order.
    """
    from . import live_event_model
    report = live_event_model.list_gui_live_events(root, since_ts=since_ts or None)
    events = report.get("events") or []
    if not events:
        return [], since_ts, since_ts_seen
    new_events: List[Dict[str, Any]] = []
    skip = since_ts_seen if since_ts else 0
    for e in events:
        if since_ts and e.get("ts") == since_ts and skip > 0:
            skip -= 1
            continue
        new_events.append(e)
    tail_ts = events[-1].get("ts")
    tail_count = 0
    for e in reversed(events):
        if e.get("ts") == tail_ts:
            tail_count += 1
        else:
            break
    return new_events, tail_ts, tail_count


# --- Control-plane HTTP dispatch (POST /api/control) ------------------------
# Reuses dv_harness.commands's extracted functions -- the SAME implementation
# dv_harness/cli.py's pause/resume/takeover/release-takeover/redirect/
# approve/correct/constraint subcommands call -- so a dashboard PAUSE (e.g.)
# is byte-for-byte the same control.json mutation + events.jsonl entry a CLI
# `dv-harness pause` would produce, not a second, possibly-drifting
# implementation. ValueError -> caller returns 400; RuntimeError (e.g.
# REDIRECT refused by an active cross-stage TAKEOVER, human_redirect's own
# exception, unchanged) -> caller returns 409.
def _dispatch_control(root: Path, body: Dict[str, Any]) -> Any:
    from .engine import DVHarness
    from . import commands

    cmd = body.get("command")
    if not cmd:
        raise ValueError("command is required")
    h = DVHarness(root)

    if cmd == "PAUSE":
        return commands.cmd_pause(h, body.get("reason", "") or "")
    if cmd == "RESUME":
        return commands.cmd_resume(h)
    if cmd == "TAKEOVER":
        return commands.cmd_takeover(h, body.get("message", "") or "")
    if cmd == "RELEASE_TAKEOVER":
        return commands.cmd_release_takeover(h)
    if cmd == "REDIRECT":
        stage = body.get("stage")
        if not stage:
            raise ValueError("stage is required for REDIRECT")
        target = commands.cmd_redirect(h, stage, body.get("reason", "") or "")
        return {"redirected_to": target}
    if cmd == "APPROVE":
        stage = body.get("stage")
        if not stage:
            raise ValueError("stage is required for APPROVE")
        return commands.cmd_approve(h, stage, body.get("note", "") or "", body.get("reviewer_id"),
                                     body.get("reviewer_confidence", "HIGH") or "HIGH")
    if cmd == "CORRECT":
        stage = body.get("stage")
        note = body.get("note")
        if not stage:
            raise ValueError("stage is required for CORRECT")
        if not note:
            raise ValueError("note is required for CORRECT")
        return commands.cmd_correct(h, stage, note, bool(body.get("reset_attempts", False)))
    if cmd == "CONSTRAINT_ADD":
        text = body.get("text")
        if not text:
            raise ValueError("text is required for CONSTRAINT_ADD")
        return commands.cmd_constraint_add(h, text)
    if cmd == "CONSTRAINT_REMOVE":
        constraint_id = body.get("constraint_id")
        if not constraint_id:
            raise ValueError("constraint_id is required for CONSTRAINT_REMOVE")
        removed = commands.cmd_constraint_remove(h, constraint_id)
        return {"removed": removed}
    if cmd == "COSIGN":
        stage = body.get("stage")
        field_path = body.get("field_path")
        if not stage:
            raise ValueError("stage is required for COSIGN")
        if not field_path:
            raise ValueError("field_path is required for COSIGN")
        if "value" not in body:
            raise ValueError("value is required for COSIGN")
        return commands.cmd_cosign(h, stage, field_path, body.get("value"), body.get("reviewer_id"),
                                    body.get("reviewer_confidence", "HIGH") or "HIGH")
    # Research / Capability Evolution (GUI-10). Routed through this same
    # dispatch on purpose: the Research card's Approve button and
    # `dv-harness approve RESEARCH_CAPABILITY_EVOLUTION` must reach one
    # implementation, not two that can drift.
    if cmd == "RESEARCH_APPROVE":
        candidate_id = body.get("candidate_id")
        note = body.get("note")
        if not candidate_id:
            raise ValueError("candidate_id is required for RESEARCH_APPROVE")
        if not note:
            raise ValueError("note is required for RESEARCH_APPROVE")
        return commands.cmd_research_approve(h, candidate_id, note, body.get("reviewer_id"),
                                              body.get("reviewer_confidence", "HIGH") or "HIGH")
    if cmd == "RESEARCH_REJECT":
        candidate_id = body.get("candidate_id")
        reason = body.get("reason")
        if not candidate_id:
            raise ValueError("candidate_id is required for RESEARCH_REJECT")
        if not reason:
            raise ValueError("reason is required for RESEARCH_REJECT")
        return commands.cmd_research_reject(h, candidate_id, reason, body.get("reviewer_id"))
    if cmd == "RESEARCH_HOLD":
        reason = body.get("reason")
        if not reason:
            raise ValueError("reason is required for RESEARCH_HOLD")
        return commands.cmd_research_hold(h, reason, body.get("candidate_id"),
                                           body.get("reviewer_id"))
    # Question Queue (WIRING_GAP_EXISTING_MODULE closure, 2026-09-07): routes a
    # reviewer's real answer/revoke through the SAME QuestionQueueStore methods
    # `dv-harness question-queue answer`/`revoke` already call -- no second
    # decision-writing mechanism, and the SAME sanctioned "a human answered" write
    # path dv_harness/gui_intake_control_plane.py's own standalone server already
    # uses. See _read_question_queue_state()'s own comment for the matching read
    # side. KeyError (unknown Q-ID / no live decision for question_key) propagates
    # unchanged -- _handle_control() already maps it to 400, matching every other
    # command's own KeyError handling above.
    if cmd == "QUESTION_ANSWER":
        from . import question_queue
        question_id = body.get("question_id")
        answer = body.get("answer")
        basis = body.get("basis")
        if not question_id:
            raise ValueError("question_id is required for QUESTION_ANSWER")
        if not answer:
            raise ValueError("answer is required for QUESTION_ANSWER")
        if not basis:
            raise ValueError("basis is required for QUESTION_ANSWER")
        store = question_queue.QuestionQueueStore(root)
        return store.answer_question(question_id, answer=answer, basis=basis,
                                      decided_by=body.get("decided_by") or "unknown")
    if cmd == "QUESTION_REVOKE":
        from . import question_queue
        question_key = body.get("question_key")
        reason = body.get("reason")
        if not question_key:
            raise ValueError("question_key is required for QUESTION_REVOKE")
        if not reason:
            raise ValueError("reason is required for QUESTION_REVOKE")
        store = question_queue.QuestionQueueStore(root)
        return store.revoke_decision(question_key, reason=reason,
                                      revoked_by=body.get("revoked_by"))
    # question_queue.request_clarification() (2026-09-07): a human signals "I don't
    # understand this question" and gets back a reworded rendering grounded entirely
    # in evidence the persisted record already carries -- never a second question
    # filing mechanism, never a new Q-ID, never a change to tier/status/blocking.
    # KeyError (unknown question_id) propagates unchanged, matching QUESTION_ANSWER/
    # QUESTION_REVOKE's own KeyError handling above.
    if cmd == "QUESTION_REQUEST_CLARIFICATION":
        from . import question_queue
        question_id = body.get("question_id")
        if not question_id:
            raise ValueError("question_id is required for QUESTION_REQUEST_CLARIFICATION")
        store = question_queue.QuestionQueueStore(root)
        return question_queue.request_clarification(
            store, question_id,
            requested_by=body.get("requested_by"),
            reason=body.get("reason"))
    raise ValueError(f"Unknown command: {cmd}")


def serve(project_root: Path, adapter_factory: Optional[Callable[[], Any]] = None):
    """Starts the dashboard's ThreadingHTTPServer and blocks (serve_forever).

    adapter_factory: see _start_background_run's docstring -- an optional
    test-only seam letting a caller (test suite) inject a fake adapter into
    any harness POST /api/start launches on this server, without touching
    the real adapter-selection path used in production.
    """
    cfg = load_config(project_root)
    state_file = project_root / ".dv-harness" / "state.json"

    # GUI-19: mint this process's session token BEFORE the server can accept
    # a single request, so there is no window in which a mutating POST is
    # reachable with no credential in existence. See dashboard_auth.py for
    # the threat model and its two disclosed residuals.
    _require_auth = bool(cfg["dashboard"].get("require_auth", True))
    _session_record = dashboard_auth.issue_session_token(
        project_root, port=int(cfg["dashboard"]["port"]),
        host=cfg["dashboard"]["host"])
    # PC-6: `token` IS the APPROVER role's token, so the banner URL and every
    # pre-role caller keep exactly the authority they had; `_role_tokens`
    # carries the VIEWER/OPERATOR credentials an operator can hand out.
    _session_token = _session_record["token"]
    _role_tokens = _session_record[dashboard_auth.ROLE_TOKENS_KEY]

    class Handler(BaseHTTPRequestHandler):
        def _send(self, data: bytes, content_type: str, status: int = 200):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            # GUI Observability (GET /api/observability): every do_GET/do_POST
            # response passes through here (directly, or via _send_json), so
            # this is the one real place to measure this process's own
            # route latency -- see _read_gui_observability_state() above.
            _route_started_at = getattr(self, "_route_start", None)
            if _route_started_at is not None:
                _record_route_latency(self.path.split("?", 1)[0],
                                       (time.monotonic() - _route_started_at) * 1000.0)

        def _send_json(self, obj: Any, status: int = 200):
            self._send(json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                        "application/json; charset=utf-8", status=status)

        # PC-6: the request body is read from the socket at most ONCE per
        # request and cached on the handler instance, because the role gate
        # has to look at /api/control's `command` BEFORE dispatch while the
        # handler still needs the same body afterwards. A second rfile.read()
        # would return nothing and turn every gated control request into an
        # empty body. BaseHTTPRequestHandler builds one instance per request,
        # so this cache never outlives the request it belongs to.
        _body_raw: Optional[bytes] = None

        def _consume_body(self) -> bytes:
            if self._body_raw is None:
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                except ValueError:
                    length = 0
                self._body_raw = self.rfile.read(length) if length > 0 else b""
            return self._body_raw

        def _control_command(self) -> Optional[str]:
            """POST /api/control's sub-command, for the role matrix only.

            Returns None when the body is absent/malformed/not an object --
            which `dashboard_auth.required_role()` treats as an UNMAPPED
            action requiring APPROVER. Not knowing which command a request
            carries is a reason to demand MORE authority, never less; the
            handler still returns its own 400 for the same malformedness once
            an authorized caller reaches it.
            """
            try:
                raw = self._consume_body()
                data = json.loads(raw.decode("utf-8")) if raw else {}
            except Exception:
                return None
            if not isinstance(data, dict):
                return None
            cmd = data.get("command")
            return cmd if isinstance(cmd, str) and cmd.strip() else None

        def _read_json_body(self) -> Dict[str, Any]:
            ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip()
            if ctype != "application/json":
                raise ValueError(f"Content-Type must be application/json, got {ctype!r}")
            raw = self._consume_body()
            if not raw:
                return {}
            try:
                data = json.loads(raw.decode("utf-8"))
            except Exception as e:
                raise ValueError(f"malformed JSON body: {e}")
            if not isinstance(data, dict):
                raise ValueError("JSON body must be an object")
            return data

        def do_GET(self):
            self._route_start = time.monotonic()
            if self.path == "/":
                # Logged once per page LOAD (not the 3s /api/state poll a
                # loaded page runs forever after) -- a reasonable proxy for
                # "a user opened this GUI", feeding user_info.py's
                # per-deployment access rollup (`dv-harness user-info`).
                from .storage import StateStore
                StateStore(project_root).event(
                    {"ts": time.time(), "event": "GUI_ACCESS",
                     "user": _access_user(), "host": _access_host()})
                self._send(HTML.encode(), "text/html; charset=utf-8")
            elif self.path == "/api/state":
                state = _read_json_file(state_file, default={})
                state["execution_mode"] = _execution_mode(project_root)
                state["overall_progress_percent"] = _overall_progress(state)
                state["coverage_credit_percent"] = _coverage_credit(project_root)
                state["failure_attribution"] = _failure_attribution(project_root)
                state["qualified_conclusion"] = _qualified_conclusion(project_root)
                review = _dv_review_pending(project_root)
                state["dv_review_pending_count"] = review["count"]
                state["dv_review_pending_fields"] = review["fields"]
                meta = _load_project_meta(project_root)
                state["db_path"] = meta["db_path"]
                state["working_path"] = meta["working_path"]
                state["configured_at"] = meta["configured_at"]
                state["configured"] = meta["configured"]
                state["running"] = _is_running(project_root)
                # Control-plane + current-stage-reason visibility (2026-08-28,
                # GUI/CLI end-to-end confirmation audit): previously this
                # endpoint never surfaced paused/takeover/constraint state or
                # WHY the current stage is stuck -- a human watching only the
                # browser could not tell a paused/taken-over run from an idle
                # one, and had to drop to `dv-harness explain`/`evidence` to
                # see blocking_reason/gate_verdict at all. Same underlying
                # data DVHarness.summary() (CLI `status`) and
                # control_plane.describe_stage() (CLI `explain`/`evidence`)
                # already compute -- reused here directly, not re-derived.
                cp_state = ControlPlane(project_root).load()
                takeover = cp_state.get("takeover", {})
                state["paused"] = bool(cp_state.get("paused"))
                state["paused_reason"] = cp_state.get("paused_reason", "") if cp_state.get("paused") else ""
                state["takeover_active"] = bool(takeover.get("active"))
                state["takeover_stage"] = takeover.get("stage") if takeover.get("active") else None
                state["constraints"] = cp_state.get("constraints", [])
                state["active_constraint_count"] = len(cp_state.get("constraints", []))
                state["dv_review_cosign_enforced"] = bool(load_config(project_root)["policy"].get("require_dv_review_cosign", False))
                state["cosigns"] = cp_state.get("cosigns", {})
                # Poster-compliance audit (2026-08-29): 6 real, evidence-backed
                # data sources that existed in the data/policy layer with no
                # GUI surface -- see the matching cards below.
                state["protocol_registry"] = _protocol_registry(project_root)
                state["environment_mode_policy"] = _environment_mode_policy(project_root)
                state["environment_mode_selected"] = _environment_mode_selected(project_root)
                state["subsystem_registry"] = _subsystem_registry(project_root)
                state["iron_rules_count"] = _iron_rules_count(project_root)
                state["qualification_tiers"] = _qualification_tiers()
                state["qualification_tier_reached"] = _qualification_tier_reached(project_root)
                state["blackboard_topics"] = _blackboard_topics(project_root)
                state["uploaded_files"] = _uploaded_files(project_root)
                current_stage = state.get("current_stage")
                if current_stage:
                    state["current_stage_detail"] = describe_stage(project_root, state, current_stage)
                # Graph-level parallel fan-out/join (2026-08-29): current_stage
                # stays parked on the fan-out's source node throughout a live
                # fan-out, so current_stage_detail above only ever explains
                # that one node -- also compute one describe_stage() block per
                # concurrently-active branch (state["active_stages"]) so the
                # dashboard can show WHY for every branch, not just the parked
                # source. Empty/omitted when there is no fan-out in flight.
                active_stages = state.get("active_stages") or []
                if active_stages:
                    state["active_stages_detail"] = describe_stages(project_root, state, active_stages)
                self._send(json.dumps(state, ensure_ascii=False).encode(), "application/json; charset=utf-8")
            elif self.path == "/api/lsf":
                jobs = load_jobs(project_root)
                self._send(json.dumps(_lsf_summary(jobs)).encode(), "application/json; charset=utf-8")
            elif self.path == "/api/lsf/jobs":
                self._send_json(load_jobs(project_root))
            elif self.path.startswith("/api/lsf/jobs/"):
                job_id = urllib.parse.unquote(self.path[len("/api/lsf/jobs/"):])
                j = get_job(project_root, job_id)
                if j is None:
                    self._send_json({"error": "NOT_FOUND", "message": f"no such job: {job_id}"}, status=404)
                else:
                    self._send_json(j)
            elif self.path == "/api/audit" or self.path.startswith("/api/audit?"):
                qs = self.path.split("?", 1)[1] if "?" in self.path else ""
                params = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
                try:
                    limit = int(params.get("limit", 50))
                except ValueError:
                    limit = 50
                self._send_json(_audit_trail(project_root, limit))
            elif self.path == "/api/gui-audit-log" or self.path.startswith("/api/gui-audit-log?"):
                qs = self.path.split("?", 1)[1] if "?" in self.path else ""
                params = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
                try:
                    limit = int(params.get("limit", 50))
                except ValueError:
                    limit = 50
                action = urllib.parse.unquote(params["action"]) if params.get("action") else None
                self._send_json(_read_gui_audit_log_state(project_root, limit, action))
            elif self.path == "/api/human-gate-center":
                # Read-only, matching /api/audit just above: this card
                # renders gui_action_safety.py's own real declarations plus
                # real ControlPlane approval status, never a dashboard-local
                # re-derivation of scope/impact/rollback -- see
                # _read_human_gate_center_state()'s own comment.
                self._send_json(_read_human_gate_center_state(project_root))
            elif self.path == "/api/graph":
                current = "ENV_CHECK"
                _st = _read_json_file(state_file)
                if _st is not None:
                    current = _st.get("current_stage", current)
                self._send(json.dumps(_graph_with_status(project_root, current)).encode(),
                           "application/json; charset=utf-8")
            elif self.path == "/api/de-explain" or self.path.startswith("/api/de-explain?"):
                from .prompts import get_de_explainer
                stage = "ENV_CHECK"
                _st = _read_json_file(state_file)
                if _st is not None:
                    stage = _st.get("current_stage", stage)
                qs = self.path.split("?", 1)[1] if "?" in self.path else ""
                params = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
                stage = params.get("stage", stage)
                self._send(json.dumps({"stage": stage, "explainer": get_de_explainer(stage)},
                                       ensure_ascii=False).encode(), "application/json; charset=utf-8")
            elif self.path == "/api/running":
                self._send_json({"running": _is_running(project_root)})
            elif self.path == "/api/stage-profile":
                # BUG FIX (2026-08-28, gui-cli-completeness-audit):
                # stage_profile_report.py renders real wall-clock/token/
                # tool-call/retry data engine.py already collects on every
                # real stage run, but had no GUI (or CLI, see cli.py
                # `stage-profile`) entry point at all.
                from . import stage_profile_report
                self._send_json({"report": stage_profile_report.render(str(project_root))})
            elif self.path == "/api/self-audit" or self.path.startswith("/api/self-audit?"):
                from . import self_audit
                qs = self.path.split("?", 1)[1] if "?" in self.path else ""
                params = urllib.parse.parse_qs(qs)  # parse_qs (not the plain dict-split every other
                                                     # GET handler above uses) so repeatable ?gate=x&gate=y works
                gate_ids = params.get("gate") or None
                smoke = params.get("smoke", ["0"])[0] in ("1", "true")
                self._send_json(self_audit.run_self_audit(project_root, gate_ids, smoke=smoke))
            elif self.path == "/api/knowledge/status":
                # Read-only status surface for the GUI -- setup itself
                # (choosing/typing the shared server path) stays a CLI-only
                # verb (`dv-harness knowledge setup`), same reasoning as
                # mark/set-stage/advance being CLI-only: this needs an
                # explicit interactive human decision about where a shared,
                # multi-user data store lives (CLAUDE.md's SSH/Remote
                # Transport Connection Intake rule), not a silent POST from
                # a form. GET is safe to expose here: it only reports the
                # config already on disk plus a live, harmless ping.
                from .knowledge_center import KnowledgeCenterClient
                cfg = load_config(project_root)  # module-level import (line 6) -- do NOT
                # re-import load_config locally here: this method already has an earlier
                # unconditional `load_config(...)` call (the /api/state branch above), and
                # Python treats a name assigned ANYWHERE in a function body as local to the
                # WHOLE function -- a local `from .config import load_config` here would
                # shadow that earlier call into an UnboundLocalError (hit and fixed once
                # already during this feature's build).
                kc = dict(cfg.get("knowledge_center") or {})
                out = {"config": kc}
                if kc.get("enabled") and kc.get("remote_root"):
                    out["ping"] = KnowledgeCenterClient(cfg, project_root).test_connection()
                self._send_json(out)
            elif self.path == "/api/session/list":
                from . import session_snapshot
                self._send_json({"sessions": session_snapshot.list_sessions(project_root)})
            elif self.path == "/api/knowledge/db-info" or self.path.startswith("/api/knowledge/db-info?"):
                from .knowledge_center import KnowledgeCenterClient
                cfg = load_config(project_root)
                if not (cfg.get("knowledge_center") or {}).get("enabled"):
                    self._send_json({"error": "NOT_CONFIGURED",
                                      "message": "knowledge center not enabled -- run `dv-harness knowledge setup`"},
                                     status=409)
                    return
                qs = self.path.split("?", 1)[1] if "?" in self.path else ""
                params = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
                res = KnowledgeCenterClient(cfg, project_root).db_info(
                    params.get("category", ""), params.get("protocol", ""),
                    params.get("action", ""), int(params.get("limit", "100")))
                self._send_json(res)
            elif self.path == "/api/coverage" or self.path.startswith("/api/coverage?"):
                qs = self.path.split("?", 1)[1] if "?" in self.path else ""
                params = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
                summary_override = urllib.parse.unquote(params["summary"]) if "summary" in params else None
                history_override = urllib.parse.unquote(params["history"]) if "history" in params else None
                self._send_json(_read_coverage_state(
                    project_root,
                    Path(summary_override) if summary_override else None,
                    Path(history_override) if history_override else None,
                ))
            elif self.path == "/api/amba" or self.path.startswith("/api/amba?"):
                # Read-only by design -- see _read_amba_registry_state()'s
                # "DISCOVERY AND PLANNING ONLY" comment: a proposed
                # vip_bind_hierarchy is approved by a human at AMBA-30/AMBA-31,
                # never through a browser POST.
                qs = self.path.split("?", 1)[1] if "?" in self.path else ""
                params = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
                registry_override = urllib.parse.unquote(params["registry"]) if "registry" in params else None
                self._send_json(_read_amba_registry_state(
                    project_root,
                    Path(registry_override) if registry_override else None,
                ))
            elif self.path == "/api/amba-connectivity-matrix" or self.path.startswith("/api/amba-connectivity-matrix?"):
                # Read-only by design -- see _read_amba_fabric_graph_state()'s
                # comment above: this renders amba_fabric_graph_ir.py's own
                # already-validated node/edge topology, never a bind decision.
                qs = self.path.split("?", 1)[1] if "?" in self.path else ""
                params = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
                graph_override = urllib.parse.unquote(params["graph"]) if "graph" in params else None
                self._send_json(_read_amba_fabric_graph_state(
                    project_root,
                    Path(graph_override) if graph_override else None,
                ))
            elif self.path == "/api/amba-path-explorer" or self.path.startswith("/api/amba-path-explorer?"):
                # Read-only by design -- see _read_amba_path_explorer_state()'s
                # comment above: this renders amba_fabric_graph_ir.py's own
                # already-validated AMBAPathIR route enumeration for one
                # caller-picked (master, slave) pair, never a route decision.
                qs = self.path.split("?", 1)[1] if "?" in self.path else ""
                params = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
                graph_override = urllib.parse.unquote(params["graph"]) if "graph" in params else None
                self._send_json(_read_amba_path_explorer_state(
                    project_root,
                    master=urllib.parse.unquote(params["master"]) if "master" in params else None,
                    slave=urllib.parse.unquote(params["slave"]) if "slave" in params else None,
                    graph_path=Path(graph_override) if graph_override else None,
                ))
            elif self.path == "/api/amba-bottleneck" or self.path.startswith("/api/amba-bottleneck?"):
                # Read-only by design -- see _read_amba_bottleneck_state()'s
                # comment above: this renders
                # amba_performance_classification.identify_bottleneck_candidate()'s
                # own real Hypothesis->Evidence->Confidence->Gap->Next-Best-Action
                # record, never a dashboard-local root-cause guess.
                qs = self.path.split("?", 1)[1] if "?" in self.path else ""
                params = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
                candidates_override = urllib.parse.unquote(params["candidates"]) if "candidates" in params else None
                self._send_json(_read_amba_bottleneck_state(
                    project_root,
                    candidates_path=Path(candidates_override) if candidates_override else None,
                ))
            elif self.path == "/api/resource-orchestrator" or self.path.startswith("/api/resource-orchestrator?"):
                # Read-only by design -- see _read_resource_orchestrator_state()'s
                # comment above: this renders resource_orchestrator.orchestrate()'s
                # own real ArbitrationPlan (VI-5's cross-job GRANTED/QUEUED/
                # DEFERRED ranking), never a dashboard-local arbitration decision.
                qs = self.path.split("?", 1)[1] if "?" in self.path else ""
                params = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
                inputs_override = urllib.parse.unquote(params["inputs"]) if "inputs" in params else None
                self._send_json(_read_resource_orchestrator_state(
                    project_root,
                    inputs_path=Path(inputs_override) if inputs_override else None,
                ))
            elif self.path == "/api/amba-performance" or self.path.startswith("/api/amba-performance?"):
                # Read-only by design -- see _read_amba_performance_state()'s
                # comment above: this renders
                # amba_performance_calculator.aggregate_port_performance()'s own
                # real PortPerformanceIR/PathPerformanceIR fields, honestly
                # showing that module's own COMPUTED/UNKNOWN/NOT_APPLICABLE
                # status per metric, never a dashboard-local performance
                # estimate.
                qs = self.path.split("?", 1)[1] if "?" in self.path else ""
                params = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
                samples_override = urllib.parse.unquote(params["samples"]) if "samples" in params else None
                self._send_json(_read_amba_performance_state(
                    project_root,
                    samples_path=Path(samples_override) if samples_override else None,
                ))
            elif self.path == "/api/amba-performance-trend" or self.path.startswith("/api/amba-performance-trend?"):
                # Read-only by design -- see _read_amba_performance_trend_state()'s
                # comment above: this renders
                # amba_performance_classification.compute_regression_delta()/
                # detect_anomaly()'s own real results across a metric's own
                # recorded periods, never a dashboard-local trend estimate.
                qs = self.path.split("?", 1)[1] if "?" in self.path else ""
                params = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
                trend_override = urllib.parse.unquote(params["trend"]) if "trend" in params else None
                self._send_json(_read_amba_performance_trend_state(
                    project_root,
                    trend_path=Path(trend_override) if trend_override else None,
                ))
            elif self.path == "/api/research":
                # Read-only. The three governance ACTIONS this card offers go
                # out through POST /api/control (RESEARCH_APPROVE /
                # RESEARCH_REJECT / RESEARCH_HOLD), never through a
                # research-specific write endpoint -- see _read_research_state().
                self._send_json(_read_research_state(project_root))
            elif self.path == "/api/generation-readiness" or self.path.startswith("/api/generation-readiness?"):
                # Read-only, matching /api/amba and /api/research above: this
                # card surfaces section 211's matrix
                # (generation_readiness.derive_generation_readiness()), never a
                # dashboard-local re-derivation of any of its rows. `deep=0`
                # mirrors the CLI's own `--no-deep` flag.
                qs = self.path.split("?", 1)[1] if "?" in self.path else ""
                params = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
                deep = params.get("deep", "1") not in ("0", "false", "False")
                self._send_json(_read_generation_readiness_state(project_root, deep=deep))
            elif self.path == "/api/self-learning-readiness":
                # Read-only, matching /api/generation-readiness just above:
                # this card renders section 55's real 22-row matrix
                # (self_learning_readiness.derive_self_learning_readiness()),
                # never a dashboard-local re-derivation of any row -- see
                # _read_self_learning_readiness_state()'s own comment.
                self._send_json(_read_self_learning_readiness_state(project_root))
            elif self.path == "/api/confidence-calibration":
                # Read-only, matching /api/generation-readiness just above:
                # this card renders confidence_calibration.calibrate()'s own
                # real per-tier reliability report, computed live -- never a
                # dashboard-local re-derivation of any tier's finding -- see
                # _read_confidence_calibration_state()'s own comment.
                self._send_json(_read_confidence_calibration_state(project_root))
            elif self.path == "/api/cross-project-mining":
                # Read-only, matching /api/confidence-calibration just above:
                # this card renders cross_project_mining.py's own real VI-2
                # production_status()/mine_cross_project_patterns() output,
                # computed live -- never a dashboard-local re-derivation of
                # any project count or cross-project pattern -- see
                # _read_cross_project_mining_state()'s own comment. No
                # project is registered/unregistered from this route.
                self._send_json(_read_cross_project_mining_state(project_root))
            elif self.path == "/api/system-smoke-proof" or self.path.startswith("/api/system-smoke-proof?"):
                # Read-only, matching /api/generation-readiness just above:
                # this card renders system_build_proof.py's own real
                # smoke-proof ladder report, read verbatim off disk -- never
                # a dashboard-local re-derivation of any rung's status, and
                # never a live re-run of the ladder -- see
                # _read_smoke_proof_state()'s own comment.
                qs = self.path.split("?", 1)[1] if "?" in self.path else ""
                params = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
                report_override = urllib.parse.unquote(params["report"]) if "report" in params else None
                self._send_json(_read_smoke_proof_state(
                    project_root, Path(report_override) if report_override else None))
            elif self.path == "/api/design-knowledge" or self.path.startswith("/api/design-knowledge?"):
                # Read-only, matching /api/generation-readiness just above:
                # this card renders design_knowledge_correlation.correlate()'s
                # own real report, never a dashboard-local re-derivation of a
                # conflict/gap/doc-vs-impl finding -- see
                # _read_design_knowledge_state()'s own comment.
                qs = self.path.split("?", 1)[1] if "?" in self.path else ""
                params = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
                sources_override = urllib.parse.unquote(params["sources"]) if "sources" in params else None
                expected_override = urllib.parse.unquote(params["expected_facts"]) if "expected_facts" in params else None
                self._send_json(_read_design_knowledge_state(
                    project_root,
                    Path(sources_override) if sources_override else None,
                    Path(expected_override) if expected_override else None,
                ))
            elif self.path == "/api/requirement-vplan-center" or self.path.startswith("/api/requirement-vplan-center?"):
                # Read-only, matching /api/design-knowledge just above: this
                # card renders requirement_contract.analyze_requirement_
                # contract_set()'s and vplan_artifact.analyze_vplan_
                # completeness()'s own real reports, never a dashboard-local
                # re-derivation of any status/gap/finding -- see
                # _read_requirement_vplan_center_state()'s own comment.
                qs = self.path.split("?", 1)[1] if "?" in self.path else ""
                params = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
                req_override = urllib.parse.unquote(params["requirements"]) if "requirements" in params else None
                vplan_override = urllib.parse.unquote(params["vplan"]) if "vplan" in params else None
                self._send_json(_read_requirement_vplan_center_state(
                    project_root,
                    Path(req_override) if req_override else None,
                    Path(vplan_override) if vplan_override else None,
                ))
            elif self.path == "/api/question-queue":
                # Read-only, matching /api/requirement-vplan-center just above: this
                # card renders question_queue.py's own real pending-question/decision/
                # metrics state, never a dashboard-local re-derivation of any tier
                # classification, escalation package or metric -- see
                # _read_question_queue_state()'s own comment. Answering/revoking a
                # decision goes out through the existing POST /api/control dispatch
                # (QUESTION_ANSWER/QUESTION_REVOKE, in _dispatch_control() below), never
                # a question-queue-specific write endpoint.
                self._send_json(_read_question_queue_state(project_root))
            elif self.path == "/api/evidence-integrity-signoff-blockers":
                # Read-only, matching /api/requirement-vplan-center just
                # above: this card renders evidence_integrity_states.
                # classify_project_evidence_integrity()'s and signoff_blocker_
                # list.derive_signoff_blockers()'s own real reports, computed
                # live off this project's own real evidence.duckdb / signoff
                # freeze store / waiver ledger / functional-coverage evidence
                # -- never a dashboard-local re-derivation of any state,
                # dimension, or blocker -- see
                # _read_evidence_integrity_signoff_blocker_state()'s own
                # comment.
                self._send_json(_read_evidence_integrity_signoff_blocker_state(project_root))
            elif self.path == "/api/test-suite-center" or self.path.startswith("/api/test-suite-center?"):
                # Read-only, matching /api/requirement-vplan-center just
                # above: this card renders test_suite_lifecycle.py's own
                # real per-pattern lifecycle report, computed live off this
                # project's real evidence.duckdb -- never a dashboard-local
                # re-derivation of any pattern's state. See
                # _read_test_suite_center_state()'s own comment.
                qs = self.path.split("?", 1)[1] if "?" in self.path else ""
                params = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
                rel_override = urllib.parse.unquote(params["relationships"]) if "relationships" in params else None
                self._send_json(_read_test_suite_center_state(
                    project_root, Path(rel_override) if rel_override else None))
            elif self.path == "/api/subsystem-system-verification" or self.path.startswith("/api/subsystem-system-verification?"):
                # Read-only, matching /api/test-suite-center just above: this
                # card renders subsystem_contract.assemble_subsystem_contract()'s,
                # system_verification_contract.assemble_system_verification_
                # contract()'s, ip_ownership_conflict.analyze_ip_ownership_
                # conflict()'s and system_resource_inventory.
                # real_cross_subsystem_findings()'s own real reports, never a
                # dashboard-local re-derivation of any field -- see
                # _read_subsystem_system_verification_state()'s own comment.
                qs = self.path.split("?", 1)[1] if "?" in self.path else ""
                params = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
                inputs_override = urllib.parse.unquote(params["inputs"]) if "inputs" in params else None
                self._send_json(_read_subsystem_system_verification_state(
                    project_root, Path(inputs_override) if inputs_override else None))
            elif self.path == "/api/verification-architecture" or self.path.startswith("/api/verification-architecture?"):
                # Read-only, matching /api/requirement-vplan-center just
                # above: this card renders verification_architecture.
                # assemble_verification_architecture()'s own real 5-matrix
                # document, never a dashboard-local re-derivation of any IR
                # field or matrix -- see
                # _read_verification_architecture_state()'s own comment.
                qs = self.path.split("?", 1)[1] if "?" in self.path else ""
                params = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
                inputs_override = urllib.parse.unquote(params["inputs"]) if "inputs" in params else None
                self._send_json(_read_verification_architecture_state(
                    project_root,
                    Path(inputs_override) if inputs_override else None,
                ))
            elif self.path == "/api/system-transaction-e2e-scoreboard" or self.path.startswith("/api/system-transaction-e2e-scoreboard?"):
                # Read-only, matching /api/verification-architecture just
                # above: this card renders system_transaction_ir.py's,
                # transaction_correlation_ir.py's and system_scoreboard_ir.py's
                # own real reports, never a dashboard-local re-derivation of
                # any composed field, correlation verdict, or scoreboard-
                # coverage finding -- see
                # _read_system_transaction_e2e_scoreboard_state()'s own
                # comment.
                qs = self.path.split("?", 1)[1] if "?" in self.path else ""
                params = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
                inputs_override = urllib.parse.unquote(params["inputs"]) if "inputs" in params else None
                self._send_json(_read_system_transaction_e2e_scoreboard_state(
                    project_root,
                    Path(inputs_override) if inputs_override else None,
                ))
            elif self.path == "/api/vip-environment-builder" or self.path.startswith("/api/vip-environment-builder?"):
                # Read-only, matching /api/verification-architecture just
                # above: this card renders protocol_capability.py's real
                # per-protocol capability_status plus vip_api_card.py's real
                # PROVEN/BLOCKED/UNPROVABLE citation report, never a
                # dashboard-local re-derivation of either -- see
                # _read_vip_environment_builder_state()'s own comment.
                qs = self.path.split("?", 1)[1] if "?" in self.path else ""
                params = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
                inputs_override = urllib.parse.unquote(params["inputs"]) if "inputs" in params else None
                self._send_json(_read_vip_environment_builder_state(
                    project_root,
                    Path(inputs_override) if inputs_override else None,
                ))
            elif self.path == "/api/loops" or self.path.startswith("/api/loops?"):
                # Read-only by design. This card OBSERVES loops; starting or
                # stopping one stays with the existing POST /api/start and the
                # existing control-plane verbs (pause/resume/takeover), which
                # already carry GUI-19's per-session token gate. Adding a
                # loop-specific write endpoint would be a second way to do
                # something that already has one.
                qs = self.path.split("?", 1)[1] if "?" in self.path else ""
                params = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
                self._send_json(_read_loop_engineering_state(
                    project_root,
                    run_id=urllib.parse.unquote(params.get("run_id", "")),
                ))
            elif self.path == "/api/agent-activity":
                # Read-only, matching /api/loops just above: this card
                # OBSERVES the real AgentTaskStore delegation ledger, it does
                # not delegate/claim/release anything itself -- see
                # _read_agent_activity_state()'s own comment (GUI-06).
                self._send_json(_read_agent_activity_state(project_root))
            elif self.path == "/api/memory" or self.path.startswith("/api/memory?"):
                # Read-only. Authoring a memory record or a vault note stays
                # CLI-only (`dv-harness memory add`, and the engine's own
                # promotion write-through), same reasoning as `knowledge
                # setup` being CLI-only below: what enters a durable
                # knowledge tier is gated on real verification evidence, not
                # on a browser form.
                qs = self.path.split("?", 1)[1] if "?" in self.path else ""
                params = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
                try:
                    note_limit = int(params.get("limit", MEMORY_VAULT_NOTE_LIMIT))
                except ValueError:
                    note_limit = MEMORY_VAULT_NOTE_LIMIT
                self._send_json(_read_memory_center_state(
                    project_root,
                    text_query=urllib.parse.unquote_plus(params.get("q", "")),
                    level_filter=urllib.parse.unquote(params.get("level", "")),
                    limit=max(1, min(note_limit, MEMORY_VAULT_SCAN_LIMIT)),
                    note_id=urllib.parse.unquote(params.get("note", "")),
                ))
            elif self.path == "/api/user-info" or self.path.startswith("/api/user-info?"):
                from . import user_info
                qs = self.path.split("?", 1)[1] if "?" in self.path else ""
                params = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
                self._send_json(user_info.summarize_user_access(
                    project_root, int(params.get("limit", "200"))))
            elif self.path == "/api/fsdb-report" or self.path.startswith("/api/fsdb-report?"):
                qs = self.path.split("?", 1)[1] if "?" in self.path else ""
                params = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
                fsdb_path = urllib.parse.unquote(params.get("path", ""))
                period = urllib.parse.unquote(params.get("period", ""))
                hier = urllib.parse.unquote(params.get("hier", ""))
                if not fsdb_path:
                    self._send_json({"error": "BAD_REQUEST", "message": "path query param is required"},
                                     status=400)
                    return
                self._send_json(_run_and_parse_fsdb_report(fsdb_path, period, hier))
            elif self.path == "/api/stats":
                from .stats_snapshot import compute_stats
                self._send_json(compute_stats(project_root))
            elif self.path == "/api/status":
                # Read-only, matching /api/loops just above: this is the
                # persistent Global Status Bar's own data source
                # (harness_status.HarnessStatusService.serve()), never a
                # dashboard-local re-derivation of harness state.
                self._send_json(_read_harness_status_state(project_root))
            elif self.path == "/api/change-impact":
                # Read-only by design -- see _read_change_impact_state()'s own
                # comment: this never runs `git diff` itself, it renders
                # change_impact.py's own already-computed selection verbatim.
                self._send_json(_read_change_impact_state(project_root))
            elif self.path == "/api/regression-tier":
                # Read-only by design -- see _read_regression_tier_state()'s
                # own comment: this never re-derives a selection, it renders
                # regression_tiers.py's own real tier policy/active tier.
                self._send_json(_read_regression_tier_state(project_root))
            elif self.path == "/api/dependency-supply-chain":
                # Read-only by design -- see _read_dependency_supply_chain_
                # state()'s own comment: this never re-derives pin/resolution/
                # advisory logic, it calls dependency_supply_chain.py's own
                # real analyze_supply_chain() verbatim.
                self._send_json(_read_dependency_supply_chain_state(project_root))
            elif self.path == "/api/intake-events":
                # Read-only by design -- see _read_intake_events_state()'s own
                # comment: this never re-parses events.jsonl itself, it calls
                # intake_events.py's own real read_intake_events() verbatim.
                self._send_json(_read_intake_events_state(project_root))
            elif self.path == "/api/pattern-runtime-state":
                # Read-only by design -- see
                # _read_pattern_runtime_state_machine_state()'s own comment:
                # this never re-derives the state machine or its
                # legal-transition table, it calls
                # pattern_runtime_state_machine.py's own real execute_verb()
                # verbatim.
                self._send_json(_read_pattern_runtime_state_machine_state(project_root))
            elif self.path == "/api/protocol-selector" or self.path.startswith("/api/protocol-selector?"):
                # Read-only by design -- see _read_protocol_selector_state()'s
                # own comment: this never re-implements protocol_router.py's
                # own resolve_protocol() normalization/tie-break logic, it
                # calls that real function verbatim, three times, over the
                # same declared evidence document.
                qs = self.path.split("?", 1)[1] if "?" in self.path else ""
                params = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
                evidence_override = urllib.parse.unquote(params["evidence"]) if "evidence" in params else None
                self._send_json(_read_protocol_selector_state(
                    project_root,
                    Path(evidence_override) if evidence_override else None,
                ))
            elif self.path == "/api/intake-baseline" or self.path.startswith("/api/intake-baseline?"):
                # Read-only by design -- see _read_intake_baseline_state()'s
                # own comment: list_intake_freezes() is always called (real,
                # safe, zero-arg); evaluate_all_intake_freezes() is called
                # ONLY when a real current-facts JSON file is found (this
                # project's own .dv-harness/intake/current_facts.json, or an
                # explicit ?current_facts=<path> override) -- never invoked
                # with fabricated facts.
                qs = self.path.split("?", 1)[1] if "?" in self.path else ""
                params = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
                facts_override = urllib.parse.unquote(params["current_facts"]) if "current_facts" in params else None
                self._send_json(_read_intake_baseline_state(
                    project_root, Path(facts_override) if facts_override else None))
            elif self.path == "/api/pattern-coverage-contribution" or \
                    self.path.startswith("/api/pattern-coverage-contribution?"):
                # Read-only by design -- see
                # _read_pattern_coverage_contribution_state()'s own comment:
                # this never re-derives coverage-checkpoint arithmetic, it
                # calls pattern_coverage_contribution.py's own real
                # compute_pattern_coverage_contribution() verbatim, and never
                # invents the required sample_attribution fact.
                qs = self.path.split("?", 1)[1] if "?" in self.path else ""
                params = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
                pcc_pattern = urllib.parse.unquote(params["pattern"]) if "pattern" in params else None
                pcc_attribution = urllib.parse.unquote(params["attribution"]) if "attribution" in params else None
                pcc_cross_defs = urllib.parse.unquote(params["cross_definitions"]) if "cross_definitions" in params else None
                self._send_json(_read_pattern_coverage_contribution_state(
                    project_root, pcc_pattern,
                    Path(pcc_attribution) if pcc_attribution else None,
                    Path(pcc_cross_defs) if pcc_cross_defs else None))
            elif self.path == "/api/build-remote-lsf-intake" or \
                    self.path.startswith("/api/build-remote-lsf-intake?"):
                # Read-only by design, and NEVER live -- see
                # _read_build_remote_lsf_intake_state()'s own comment: this
                # NEVER calls preflight.run_preflight()/resolve_transport()
                # itself; it only reads an already-declared PreflightResult/
                # TransportDecision-shaped JSON document off disk and calls
                # build_remote_lsf_intake.py's own real fields_from_
                # preflight()/evaluate_build_remote_lsf_readiness() verbatim.
                qs = self.path.split("?", 1)[1] if "?" in self.path else ""
                params = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
                brl_inputs_override = urllib.parse.unquote(params["inputs"]) if "inputs" in params else None
                self._send_json(_read_build_remote_lsf_intake_state(
                    project_root, Path(brl_inputs_override) if brl_inputs_override else None))
            elif self.path == "/api/scenario-pattern-command-txt-correspondence" or \
                    self.path.startswith("/api/scenario-pattern-command-txt-correspondence?"):
                # Read-only by design -- see
                # _read_scenario_pattern_command_txt_correspondence_state()'s
                # own comment: this never re-derives the VIP-scenario-pattern
                # <-> branch_b* usage cross-check, it calls
                # scenario_pattern_command_txt_correspondence.py's own real
                # analyze_scenario_pattern_command_txt_correspondence()
                # verbatim. parse_qs (not the plain dict-split most other GET
                # handlers use) so repeatable ?command_file=x&command_file=y
                # works, the same reasoning /api/self-audit's ?gate= already
                # documents.
                qs = self.path.split("?", 1)[1] if "?" in self.path else ""
                params = urllib.parse.parse_qs(qs)
                _cap_report = params.get("capability_report", [None])[0]
                self._send_json(_read_scenario_pattern_command_txt_correspondence_state(
                    project_root,
                    Path(_cap_report) if _cap_report else None,
                    params.get("command_file") or None,
                ))
            elif self.path == "/api/orphaned-fork-detection" or self.path.startswith("/api/orphaned-fork-detection?"):
                # Read-only, matching /api/multi-vip-cooperation just below:
                # this card renders orphaned_fork_detection.py's own real
                # branch_b*-dispatch/wait pairing report, never a dashboard-
                # local re-derivation of any finding -- see
                # _read_orphaned_fork_detection_state()'s own comment.
                qs = self.path.split("?", 1)[1] if "?" in self.path else ""
                params = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
                inputs_override = urllib.parse.unquote(params["inputs"]) if "inputs" in params else None
                self._send_json(_read_orphaned_fork_detection_state(
                    project_root, Path(inputs_override) if inputs_override else None))
            elif self.path == "/api/multi-vip-cooperation" or self.path.startswith("/api/multi-vip-cooperation?"):
                # Read-only, matching /api/orphaned-fork-detection just
                # above: this card renders multi_vip_cooperation_
                # architecting.py's own real build_multi_vip_cooperation()
                # report, never a dashboard-local re-derivation of any
                # cooperation/architecture/sequencing status -- see
                # _read_multi_vip_cooperation_state()'s own comment.
                qs = self.path.split("?", 1)[1] if "?" in self.path else ""
                params = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
                inputs_override = urllib.parse.unquote(params["inputs"]) if "inputs" in params else None
                self._send_json(_read_multi_vip_cooperation_state(
                    project_root, Path(inputs_override) if inputs_override else None))
            elif self.path == "/api/dut-errata-correlation" or self.path.startswith("/api/dut-errata-correlation?"):
                # Read-only, matching /api/multi-vip-cooperation just above:
                # this card renders dut_errata_correlation.py's own real
                # analyze_errata() report, never a dashboard-local
                # re-derivation of any erratum's RTL/register correlation --
                # see _read_dut_errata_correlation_state()'s own comment.
                qs = self.path.split("?", 1)[1] if "?" in self.path else ""
                params = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
                inputs_override = urllib.parse.unquote(params["inputs"]) if "inputs" in params else None
                self._send_json(_read_dut_errata_correlation_state(
                    project_root, Path(inputs_override) if inputs_override else None))
            elif self.path == "/api/memory-quality-policy":
                # Read-only by design -- see _read_memory_quality_policy_
                # state()'s own comment: this never re-derives a stale/
                # never-confirmed/duplicate decision itself, it calls
                # memory_quality_policy.py's own real evaluate_memory_
                # quality() verbatim, and never the apply() half.
                self._send_json(_read_memory_quality_policy_state(project_root))
            elif self.path == "/api/notifications":
                # Read-only by design -- see _read_notification_center_state()'s
                # own comment: no transport is ever constructed here, and the
                # change-only history is filtered, never recomputed.
                self._send_json(_read_notification_center_state(project_root))
            elif self.path == "/api/observability":
                # Read-only by design -- see _read_gui_observability_state()'s
                # own comment: this dashboard process's own self-measured
                # route latency plus the real events.jsonl backlog/staleness.
                self._send_json(_read_gui_observability_state(project_root))
            elif self.path == "/api/events/stream" or self.path.startswith("/api/events/stream?"):
                # SSE push transport for live_event_model.py's own eleven
                # GUI_* events -- see _new_gui_live_events()'s own comment
                # above. Read-only, matching every other GET route: it never
                # emits an event itself, only forwards ones a real writer
                # already recorded through live_event_model.emit(). Does NOT
                # go through self._send()/_send_json() (there is no bounded
                # response to send -- the whole point is an open-ended
                # stream), so it contributes nothing to
                # _record_route_latency()'s per-route samples and touches no
                # other route's behaviour. One handler thread per connected
                # tab; ThreadingHTTPServer.daemon_threads is True (stdlib
                # default), so a tab left open never blocks another request
                # or this process's own shutdown.
                qs = self.path.split("?", 1)[1] if "?" in self.path else ""
                params = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                from .engine import now as _now_iso
                # Absent ?since=, start from THIS connection's own open time --
                # a newly-opened tab gets only future events, never a replay
                # of the whole backlog. An explicit ?since= (including an
                # empty one, which sorts before every real ISO timestamp) lets
                # a reconnecting client ask for exactly what it missed.
                since_ts = (urllib.parse.unquote(params["since"]) if "since" in params
                           else _now_iso())
                since_ts_seen = 0
                idle_polls = 0
                try:
                    while True:
                        new_events, since_ts, since_ts_seen = _new_gui_live_events(
                            project_root, since_ts, since_ts_seen)
                        if new_events:
                            for event in new_events:
                                frame = "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
                                self.wfile.write(frame.encode("utf-8"))
                            self.wfile.flush()
                            idle_polls = 0
                        else:
                            idle_polls += 1
                            if idle_polls % 20 == 0:  # ~20s SSE comment heartbeat
                                self.wfile.write(b": keep-alive\n\n")
                                self.wfile.flush()
                        time.sleep(1.0)
                except OSError:
                    return  # the browser tab navigated away/closed; not a server error
            elif self.path == "/api/verification-strategy" or self.path.startswith("/api/verification-strategy?"):
                # Read-only, matching /api/generation-readiness just above:
                # this card renders verification_strategy.execute_verb()'s
                # own real VI-4 recommendation report, computed live off this
                # project's real coverage-closure/failure-density/protocol/
                # topology signals -- never a dashboard-local re-derivation
                # of any signal or verdict -- see
                # _read_verification_strategy_state()'s own comment.
                qs = self.path.split("?", 1)[1] if "?" in self.path else ""
                params = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
                verb = urllib.parse.unquote(params.get("verb", "recommend"))
                goal = urllib.parse.unquote(params.get("goal", ""))
                scope_override = urllib.parse.unquote(params["scope"]) if "scope" in params else None
                protocol_override = urllib.parse.unquote(params["protocol"]) if "protocol" in params else None
                holes_override = urllib.parse.unquote(params["holes"]) if "holes" in params else None
                self._send_json(_read_verification_strategy_state(
                    project_root, verb=verb, goal=goal, scope=scope_override,
                    protocol=protocol_override, holes_path=holes_override))
            elif self.path == "/view/dashboard":
                # P2-1: a genuinely SEPARATE, SMALLER executive-summary
                # document -- built via web_layout.page_shell(), never a
                # touch to the "/" route's own HTML/CSS/JS string above --
                # implementing GUI-13's own required minimum metric set
                # (Overall Readiness, Verification Closure, Requirements,
                # vPlan, Regression PASS Rate, Functional/Code Coverage,
                # Assertion Closure, Critical Failures, Open Waivers,
                # Blocked Requirements, Active LSF Jobs, Recent Coverage
                # Delta). This is also the proof that web_layout.py is real
                # and load-bearing (the dropped P1-2 item's own stated
                # purpose), since a live server response calling it is
                # sufficient without touching working "/" route code.
                #
                # Every metric below is READ from an already-real,
                # already-tested producer this same file (or a sibling
                # module) already calls elsewhere on this page -- never a
                # second, dashboard-local re-derivation of any verdict:
                #   Overall Readiness        <- HarnessStatusIR.harness.state
                #     (harness_status.HarnessStatusService, the SAME
                #     worst-wins fold /api/status already serves)
                #   Verification Closure     <- ...closure.system
                #     (system_closure_aggregator's real 12-dimension
                #     worst-wins CLOSED/NOT_CLOSED/INCOMPLETE_EVIDENCE fold)
                #   Requirements              <- ...closure.requirement, plus
                #     requirement_contract.py's real per-requirement
                #     derived-status counts via
                #     _read_requirement_vplan_center_state()
                #   vPlan                     <- ...closure.vplan, plus
                #     vplan_artifact.py's real per-dimension completeness
                #     verdict via the same reader
                #   Regression PASS Rate      <- execution.passed_jobs /
                #     (passed_jobs + failed_jobs), both real LSF-derived
                #     counts (regression_reporter.load_jobs() ->
                #     dashboard._lsf_summary(), the same pipeline
                #     ExecutionIR itself is built from)
                #   Functional/Code Coverage  <- ...closure.functional_
                #     coverage / ...closure.code_coverage (the latter is
                #     honestly UNKNOWN by that module's own documented
                #     design -- GF-AT-28, never fabricated)
                #   Assertion Closure         <- ...closure.assertion
                #   Critical Failures         <- blockers.critical_failures
                #     (+ blockers.critical_unknown, kept separate per
                #     GF-AT-28: an unmeasured subsystem is never counted as
                #     a confirmed failure)
                #   Open Waivers              <- waiver_store.status_report()'s
                #     own real ledger (total recorded + not-VALID count)
                #   Blocked Requirements      <- a real count of
                #     requirement_contract.py's own re-derived
                #     CONTRADICTORY status among the requirements this
                #     project has declared -- "ARBITRATION IS NOT HERE": a
                #     CONTRADICTORY requirement STOPS there by that
                #     module's own design, so this is the honest "blocked"
                #     signal, never a guessed synonym.
                #   Active LSF Jobs           <- execution.running_jobs
                #     (+ execution.queued_jobs)
                #   Recent Coverage Delta     <- coverage_analysis.
                #     compute_coverage_trend()'s own real delta, via
                #     _read_coverage_state() (requires >= 2 recorded
                #     coverage-history samples; honestly UNKNOWN otherwise,
                #     never a fabricated 0%)
                #
                # Read-only end to end -- no build, gate, or approval is
                # touched, and there is deliberately no write endpoint of
                # its own, matching every sibling read-only card on this
                # page.
                from . import web_layout
                from . import waiver_store as _view_ws
                from html import escape as _view_esc

                _hs = _read_harness_status_state(project_root)
                _status = _hs.get("status") or {}
                _harness = _status.get("harness") or {}
                _closure = _status.get("closure") or {}
                _execution = _status.get("execution") or {}
                _blockers = _status.get("blockers") or {}

                _rvc = _read_requirement_vplan_center_state(project_root)
                _req_report = _rvc.get("requirement_report") or {}
                _req_rows = _req_report.get("requirements") or []
                _req_status_counts = _req_report.get("status_counts") or {}
                _blocked_requirements = sum(
                    1 for _r in _req_rows
                    if _r.get("derived_status") == "CONTRADICTORY")
                _vplan_report = _rvc.get("vplan_report") or {}
                _vplan_overall = _vplan_report.get("overall_status")

                try:
                    _waiver_report = _view_ws.status_report(project_root)
                except Exception as _e:
                    _waiver_report = {"status": "NOT_AVAILABLE",
                                       "waivers": [], "not_valid": None,
                                       "reason": str(_e)}

                _cov = _read_coverage_state(project_root)
                _trend = _cov.get("trend") if _cov.get("available") else None
                _coverage_delta = _trend.get("delta") if _trend else None
                _coverage_delta_trend = _trend.get("trend") if _trend else None

                _passed = _execution.get("passed_jobs")
                _failed = _execution.get("failed_jobs")
                if (isinstance(_passed, int) and isinstance(_failed, int)
                        and (_passed + _failed) > 0):
                    _pass_rate = round(100.0 * _passed / (_passed + _failed), 1)
                else:
                    _pass_rate = None

                def _metric_card(card_id: str, title: str, value, detail: str = "") -> str:
                    _val = _view_esc(str(value if value is not None else "UNKNOWN"))
                    _body = (f'<p style="font-size:22px;font-weight:bold;'
                             f'margin:4px 0">{_val}</p>')
                    if detail:
                        _body += (f'<p style="color:#6b7280;font-size:12px;'
                                   f'margin:0">{_view_esc(detail)}</p>')
                    return web_layout.render_card(card_id, title, _body)

                _cards = [
                    _metric_card("overallReadiness", "Overall Readiness",
                                 _harness.get("state"),
                                 "worst-wins fold across every real "
                                 "HarnessStatusIR dimension"),
                    _metric_card("verificationClosure", "Verification Closure",
                                 _closure.get("system"),
                                 "system_closure_aggregator's 12-dimension "
                                 "worst-wins verdict"),
                    _metric_card(
                        "requirements", "Requirements",
                        _closure.get("requirement"),
                        (f"{_req_status_counts.get('COMPLETE', 0)} COMPLETE / "
                         f"{sum(_req_status_counts.values())} analyzed")
                        if _req_status_counts else
                        "no requirements.json declared yet"),
                    _metric_card(
                        "vplan", "vPlan", _closure.get("vplan"),
                        f"vplan_artifact overall: {_vplan_overall}"
                        if _vplan_overall else "no vplan.json declared yet"),
                    _metric_card(
                        "regressionPassRate", "Regression PASS Rate",
                        (f"{_pass_rate}%" if _pass_rate is not None else "UNKNOWN"),
                        (f"{_passed} passed / {_failed} failed"
                         if isinstance(_passed, int) and isinstance(_failed, int)
                         else "no LSF jobs recorded yet")),
                    _metric_card(
                        "functionalCodeCoverage", "Functional / Code Coverage",
                        f"functional: {_closure.get('functional_coverage')}",
                        f"code: {_closure.get('code_coverage')} (no distinct "
                        f"code-coverage row exists yet -- honestly UNKNOWN)"),
                    _metric_card("assertionClosure", "Assertion Closure",
                                 _closure.get("assertion")),
                    _metric_card(
                        "criticalFailures", "Critical Failures",
                        _blockers.get("critical_failures", 0),
                        f"{_blockers.get('critical_unknown', 0)} additional "
                        f"subsystem(s) UNKNOWN (never counted as failures)"),
                    _metric_card(
                        "openWaivers", "Open Waivers",
                        len(_waiver_report.get("waivers") or []),
                        (f"{_waiver_report.get('not_valid')} not VALID"
                         if _waiver_report.get("not_valid") is not None
                         else _waiver_report.get("reason", ""))),
                    _metric_card(
                        "blockedRequirements", "Blocked Requirements",
                        _blocked_requirements,
                        "requirement_contract.py-derived CONTRADICTORY count"),
                    _metric_card(
                        "activeLsfJobs", "Active LSF Jobs",
                        _execution.get("running_jobs"),
                        f"{_execution.get('queued_jobs')} queued"),
                    _metric_card(
                        "recentCoverageDelta", "Recent Coverage Delta",
                        (f"{_coverage_delta:+.1f}% ({_coverage_delta_trend})"
                         if _coverage_delta is not None else "UNKNOWN"),
                        ("" if _coverage_delta is not None else
                         "requires >= 2 recorded coverage-history samples")),
                ]

                _routes = ([("main", "Dashboard", "/"),
                            ("view_dashboard", "Executive View", "/view/dashboard")]
                           + _external_gui_server_nav_routes(project_root))
                _body_html = (
                    web_layout.render_nav(_routes, active="view_dashboard")
                    + web_layout.render_status_bar_partial()
                    + '<main><h1>Executive Dashboard</h1>'
                    + '<p style="color:#6b7280">Read-only. GUI-13 minimum '
                      'metric set, computed live from real, already-tested '
                      'producers -- see the /view/dashboard route\'s own '
                      'comment in dashboard.py.</p>'
                    + "".join(_cards) + "</main>"
                )
                _doc = web_layout.page_shell(
                    "Executive Dashboard", _body_html, active_route="view_dashboard")
                self._send(_doc.encode("utf-8"), "text/html; charset=utf-8")
            else:
                self._send(b"not found", "text/plain", status=404)

        # GUI-19: the single access-control choke point. Deliberately here,
        # in front of the path dispatch below, rather than as a per-handler
        # decorator -- a POST endpoint added later is gated by EXISTING, not
        # by whoever adds it remembering to opt it in. Every branch below
        # mutates real state (control-plane APPROVE/COSIGN/TAKEOVER, waiver
        # authoring, signoff export, policy writes, uploads, harness start),
        # so there is no read-only POST to carve out.
        # PC-6 adds the ROLE half in the SAME call: authentication decides
        # whether the caller holds one of this session's tokens, the matrix
        # decides whether that token's role reaches THIS action. For
        # /api/control the action is the sub-command, so it is read here --
        # one endpoint carries both "pause the run" and "approve SIGNOFF".
        def _authorized(self) -> bool:
            path = self.path.split("?", 1)[0]
            command = (self._control_command()
                       if path == dashboard_auth.CONTROL_ENDPOINT else None)
            decision = dashboard_auth.authorize_detail(
                _session_token, self.headers, self.path, method="POST",
                require_auth=_require_auth, role_tokens=_role_tokens,
                control_command=command)
            if decision["allowed"]:
                return True
            # Recorded on the same real audit trail every other dashboard
            # action lands on -- a refused approval attempt is exactly the
            # kind of event `dv-harness audit` exists to be able to show.
            try:
                from .storage import StateStore
                StateStore(project_root).event(
                    {"ts": time.time(), "event": "DASHBOARD_AUTH_DENIED",
                     "path": path, "reason": decision["reason"],
                     "action": decision["action"], "role": decision["role"],
                     "required_role": decision["required_role"],
                     "user": _access_user(), "host": _access_host()})
            except Exception:
                pass  # an audit-write failure must never turn a denial into a 500
            self._send_json(
                dashboard_auth.denial_response(
                    decision["reason"], role=decision["role"],
                    required_role=decision["required_role"],
                    action=decision["action"]),
                status=403)
            return False

        # ---- Human Control Plane / setup / start ---------------------------
        def do_POST(self):
            self._route_start = time.monotonic()
            if not self._authorized():
                return
            # Dispatch on the path WITHOUT its query string: the session token
            # may legitimately arrive as ?token=... (the form dashboard_auth's
            # startup URL carries), and every branch below takes its real
            # arguments from the JSON body, never from the query.
            path = self.path.split("?", 1)[0]
            if path == "/api/setup":
                self._handle_setup()
            elif path == "/api/start":
                self._handle_start()
            elif path == "/api/control":
                self._handle_control()
            elif path == "/api/config":
                self._handle_config()
            elif path == "/api/session/save":
                self._handle_session_save()
            elif path == "/api/session/restore":
                self._handle_session_restore()
            elif path == "/api/upload":
                self._handle_upload()
            elif path == "/api/signoff-export":
                self._handle_signoff_export()
            elif path == "/api/waiver":
                self._handle_waiver_submit()
            else:
                self._send_json({"error": "NOT_FOUND", "message": f"no such POST endpoint: {path}"},
                                 status=404)

        def _handle_session_save(self):
            from . import session_snapshot
            from .engine import DVHarness
            from .control_plane import now as cp_now
            try:
                body = self._read_json_body()
            except ValueError as e:
                self._send_json({"error": "BAD_REQUEST", "message": str(e)}, status=400)
                return
            try:
                manifest = session_snapshot.save_session(project_root, body.get("name"), body.get("note", ""))
            except FileExistsError as e:
                self._send_json({"error": "CONFLICT", "message": str(e)}, status=409)
                return
            DVHarness(project_root).store.event(
                {"ts": cp_now(), "event": "SESSION_SAVED", "name": manifest["name"]})
            self._send_json(manifest)

        def _handle_session_restore(self):
            from . import session_snapshot
            from .engine import DVHarness
            from .control_plane import now as cp_now
            try:
                body = self._read_json_body()
            except ValueError as e:
                self._send_json({"error": "BAD_REQUEST", "message": str(e)}, status=400)
                return
            name = body.get("name")
            if not name:
                self._send_json({"error": "BAD_REQUEST", "message": "name is required"}, status=400)
                return
            try:
                result = session_snapshot.restore_session(
                    project_root, name, backup_current=not body.get("no_backup", False))
            except FileNotFoundError as e:
                self._send_json({"error": "NOT_FOUND", "message": str(e)}, status=404)
                return
            # events.jsonl is deliberately excluded from what restore copies
            # back (session_snapshot.RESTORE_FILES) -- an append-only audit
            # log should never be destructively rewound, so this marker
            # lands on the same continuous, live log (same reasoning as the
            # CLI's `restore-session` branch).
            DVHarness(project_root).store.event(
                {"ts": cp_now(), "event": "SESSION_RESTORED", "name": name,
                 "auto_backup": result.get("auto_backup")})
            self._send_json(result)

        # POST /api/config: the one write path for .dv-harness/config.json's
        # policy block from the dashboard (CLI equivalent: `dv-harness config
        # set`). Deliberately scoped to a single allow-listed key today
        # (require_dv_review_cosign) rather than accepting an arbitrary
        # policy key/value -- widening this is a real design decision
        # (validation per key, effect on running gates) left for when a
        # second policy field actually needs a GUI/CLI toggle.
        _CONFIGURABLE_POLICY_KEYS = {"require_dv_review_cosign"}

        def _handle_config(self):
            try:
                body = self._read_json_body()
            except ValueError as e:
                self._send_json({"error": "BAD_REQUEST", "message": str(e)}, status=400)
                return
            key = body.get("key")
            if key not in self._CONFIGURABLE_POLICY_KEYS:
                self._send_json({"error": "BAD_REQUEST",
                                  "message": f"key must be one of {sorted(self._CONFIGURABLE_POLICY_KEYS)}"},
                                 status=400)
                return
            if "value" not in body:
                self._send_json({"error": "BAD_REQUEST", "message": "value is required"}, status=400)
                return
            cfg = load_config(project_root)
            cfg["policy"][key] = bool(body.get("value"))
            save_config(project_root, cfg)
            self._send_json({"saved": True, "policy": cfg["policy"]})

        # POST /api/upload: base64-encoded file content in a JSON body (see
        # _UPLOAD_CATEGORIES's module-level docstring for why -- Python 3.13+
        # removed the cgi module, so this deliberately avoids a hand-rolled
        # multipart/form-data parser). Every rejection path below returns
        # before touching disk or (for the size check) before calling
        # base64.b64decode at all.
        def _handle_upload(self):
            try:
                body = self._read_json_body()
            except ValueError as e:
                self._send_json({"error": "BAD_REQUEST", "message": str(e)}, status=400)
                return

            category = body.get("category")
            if category not in _UPLOAD_CATEGORIES:
                self._send_json({"error": "BAD_REQUEST",
                                  "message": f"category must be one of {list(_UPLOAD_CATEGORIES)}"}, status=400)
                return

            filename = body.get("filename")
            if not isinstance(filename, str):
                self._send_json({"error": "BAD_REQUEST", "message": "filename is required"}, status=400)
                return
            try:
                _validate_upload_filename(filename)
            except ValueError as e:
                self._send_json({"error": "BAD_REQUEST", "message": str(e)}, status=400)
                return

            content_b64 = body.get("content_b64")
            if not isinstance(content_b64, str):
                self._send_json({"error": "BAD_REQUEST", "message": "content_b64 is required"}, status=400)
                return
            # Reject an oversized payload BEFORE decoding -- see
            # _MAX_UPLOAD_B64_CHARS's definition above.
            if len(content_b64) > _MAX_UPLOAD_B64_CHARS:
                self._send_json({"error": "BAD_REQUEST",
                                  "message": f"file too large: exceeds {_MAX_UPLOAD_DECODED_BYTES} bytes decoded"},
                                 status=400)
                return
            try:
                content = base64.b64decode(content_b64, validate=True)
            except (binascii.Error, ValueError) as e:
                self._send_json({"error": "BAD_REQUEST", "message": f"malformed base64 content: {e}"}, status=400)
                return

            cat_dir = _upload_root(project_root) / category
            cat_dir.mkdir(parents=True, exist_ok=True)
            saved_filename = _unique_upload_filename(cat_dir, filename)
            (cat_dir / saved_filename).write_bytes(content)
            rel_path = (Path(".dv-harness") / "uploads" / category / saved_filename).as_posix()
            self._send_json({"status": "OK", "category": category, "saved_filename": saved_filename,
                              "path": rel_path, "bytes": len(content)})

        # POST /api/signoff-export: {"out_dir": "..."} (optional -- defaults
        # under .dv-harness/signoff-export/<timestamp>/ if omitted). Calls
        # signoff_export.collect_signoff_bundle() directly, in this same
        # process -- no subprocess/CLI shell-out -- same pattern as
        # _handle_session_save calling session_snapshot.save_session()
        # directly above.
        def _handle_signoff_export(self):
            from . import signoff_export
            try:
                body = self._read_json_body()
            except ValueError as e:
                self._send_json({"error": "BAD_REQUEST", "message": str(e)}, status=400)
                return
            out_dir_raw = body.get("out_dir")
            out_dir = Path(out_dir_raw) if out_dir_raw else _default_signoff_export_dir(project_root)
            result = signoff_export.collect_signoff_bundle(project_root, out_dir)
            self._send_json(result)

        # POST /api/waiver -- the human-facing writer of the durable waiver
        # ledger the three waiver gate scripts now read as their source of
        # truth (see waiver_store.py's module docstring). Two accepted bodies,
        # dispatched by append_waiver(): a full section 237 record (carries
        # "waiver_id"; validated by record_waiver(), which refuses a stored
        # "status", an unmeasured revalidation trigger, an incomplete scope or
        # a duplicate id) and the original 4-field {"gate_id", "item_id",
        # "approved", "evidence"} shape. WaiverStoreError subclasses
        # ValueError, so every refusal reaches the caller as a 400 with its
        # real reason. Calls waiver_store directly, in this same process -- no
        # subprocess -- same pattern as _handle_signoff_export calling
        # signoff_export.collect_signoff_bundle() directly above.
        def _handle_waiver_submit(self):
            from . import waiver_store
            try:
                body = self._read_json_body()
            except ValueError as e:
                self._send_json({"error": "BAD_REQUEST", "message": str(e)}, status=400)
                return
            try:
                record = waiver_store.append_waiver(project_root, body)
            except ValueError as e:
                self._send_json({"error": "BAD_REQUEST", "message": str(e)}, status=400)
                return
            self._send_json({"status": "OK", "waiver": record})

        def _handle_setup(self):
            try:
                body = self._read_json_body()
            except ValueError as e:
                self._send_json({"error": "BAD_REQUEST", "message": str(e)}, status=400)
                return
            db_path = body.get("db_path")
            working_path = body.get("working_path")
            if not db_path or not working_path:
                self._send_json({"error": "BAD_REQUEST",
                                  "message": "db_path and working_path are both required"}, status=400)
                return
            meta = _save_project_meta(project_root, str(db_path), str(working_path))
            self._send_json({"saved": True, **meta})

        def _handle_start(self):
            try:
                body = self._read_json_body()
            except ValueError as e:
                self._send_json({"error": "BAD_REQUEST", "message": str(e)}, status=400)
                return
            meta = _load_project_meta(project_root)
            if not meta["configured"]:
                self._send_json({"error": "NOT_CONFIGURED",
                                  "message": "POST /api/setup (db_path/working_path) before starting the harness"},
                                 status=400)
                return
            goal = body.get("goal")
            if not goal:
                self._send_json({"error": "BAD_REQUEST", "message": "goal is required"}, status=400)
                return
            loop = bool(body.get("loop", False))
            # M6 C1 (CAP-M6-C1-001) + GAP-V2-002 remediation
            # (CAP-M6-GAPV2002-001) + CAP-M5M6-VLEVEL-001 +
            # M6-TASK-BOUNDARY-PRODUCTION-001: additive, optional
            # counterpart to cli.py's --protocols/--dut-role/--level/
            # --task-boundary-*/--generate/--generate-out/--generate-manifest.
            # Omitted (the pre-C1 shape) -> identical to before any of
            # these closures.
            protocols_raw = body.get("protocols") or []
            protocols = tuple(str(p).strip() for p in protocols_raw if str(p).strip())
            role_raw = body.get("role")
            role = str(role_raw).strip() or None if role_raw else None
            level_raw = body.get("level")
            level = str(level_raw).strip() or None if level_raw else None
            generation_request = body.get("generation_request") if body.get("generate") else None
            if body.get("generate") and generation_request is None:
                generation_request = {}
            generate_out = body.get("generate_out")
            generation_out_dir = Path(generate_out) if generate_out else None
            # M6-TASK-BOUNDARY-PRODUCTION-001: a real TaskBoundary is built
            # ONLY when the caller's JSON body carries a "task_boundary"
            # object -- omitted (the pre-existing shape), task_boundary
            # stays None, byte-identical to before this task.
            task_boundary_raw = body.get("task_boundary")
            task_boundary = None
            if task_boundary_raw:
                from . import task_boundary_conformance as _tbc
                task_boundary = _tbc.TaskBoundary.from_dict(task_boundary_raw)
            try:
                _start_background_run(project_root, str(goal), loop, adapter_factory=adapter_factory,
                                      protocols=protocols, role=role, level=level,
                                      task_boundary=task_boundary,
                                      generation_request=generation_request,
                                      generation_out_dir=generation_out_dir)
            except RuntimeError as e:
                self._send_json({"error": "ALREADY_RUNNING", "message": str(e)}, status=409)
                return
            self._send_json({"started": True, "loop": loop, "goal": goal})

        def _handle_control(self):
            try:
                body = self._read_json_body()
            except ValueError as e:
                self._send_json({"error": "BAD_REQUEST", "message": str(e)}, status=400)
                return
            try:
                # Structured GUI Audit Log (2026-09-06, dv_harness/
                # gui_audit_log.py): wrap_dispatch() runs the real
                # _dispatch_control() unchanged and writes exactly one
                # who/when/before/after/evidence/approval/result record for
                # it, via the SAME StateStore.event() every commands.cmd_*
                # generic {"ts","cmd",...} event already goes through --
                # never a second audit file.
                result = gui_audit_log.wrap_dispatch(project_root, body, _dispatch_control)
            except ValueError as e:
                self._send_json({"error": "BAD_REQUEST", "message": str(e)}, status=400)
                return
            except PermissionError as e:
                # capability_evolution.HumanApprovalRequiredError /
                # ProductionWriteNotAuthorizedError, the Level B -> Level C
                # refusals. A gate saying "a human has not authorized this" is
                # a 403 answer, not a 500 crash -- and its message names the
                # real command that would authorize it.
                self._send_json({"error": "FORBIDDEN", "message": str(e)}, status=403)
                return
            except RuntimeError as e:
                self._send_json({"error": "CONFLICT", "message": str(e)}, status=409)
                return
            except KeyError as e:
                self._send_json({"error": "BAD_REQUEST", "message": f"missing field: {e}"}, status=400)
                return
            self._send_json({"result": result})

        def log_message(self, *args):
            pass

    host = cfg["dashboard"]["host"]
    port = int(cfg["dashboard"]["port"])
    print(dashboard_auth.startup_banner(host, port, _session_token, _require_auth,
                                        role_tokens=_role_tokens))
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-root", default=".")
    a = ap.parse_args()
    serve(Path(a.project_root).resolve())
