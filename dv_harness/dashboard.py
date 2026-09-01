from __future__ import annotations
import base64, binascii, json, os, re, tempfile, threading, time, traceback, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from .config import load_config, save_config
from .regression_reporter import load_jobs, get_job
from .gates import extract_evidence_blocks, JUDGMENT_FIELDS, CCL_SKIPPABLE, REVIEWER_CONFIDENCE_LEVELS, _iter_judgment_targets
from .models import Stage
from .storage import _atomic_replace
from .control_plane import ControlPlane, describe_stage, describe_stages


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
.PASS,.CLOSED,.SCRIPT_SMOKE_PASS{color:#25845b}.FAIL,.BLOCKED,.SCRIPT_SMOKE_FAIL{color:#b84444}
.RUNNING,.RETRY{color:#2457a6}.PARTIAL,.WAIT_USER,.NO_SOURCE_DATA,.GATE_TOOL_MISSING{color:#b36a00}.NOT_STARTED{color:#9aa6bd}
.protoTile{cursor:pointer}.protoTile:hover{border-color:#2457a6}.protoTile.selected{border-color:#2457a6;background:#eaf1fb}
.modeTile.mode-selected{border-color:#2457a6;background:#eaf1fb}
.tier-reached{border-color:#25845b;background:#e3f7ea}.tier-unreached{opacity:.5}
code{background:#eef2f7;padding:3px 5px}
.note{color:#8a97b3;font-size:12px}
.err{color:#b84444}
.ok{color:#25845b}
.ctrlrow{margin:8px 0;display:flex;flex-wrap:wrap;gap:8px;align-items:center;font-size:13px}
.ctrlrow input[type=text],.ctrlrow input:not([type]),.ctrlrow select{padding:4px 6px;border:1px solid #d9e1ec;border-radius:5px}
.ctrlrow label{display:flex;align-items:center;gap:4px}
button{background:#2457a6;color:white;border:none;border-radius:6px;padding:6px 12px;cursor:pointer;font-size:13px}
button:disabled{background:#b7c3d9;cursor:not-allowed}
button.secondary{background:#5a6b8c}
input,select{font-size:13px}
#controlResult,#setupResult,#runResult{background:#f7f9fc;border:1px solid #e3e9f2;border-radius:6px;padding:8px;white-space:pre-wrap;font-size:12px;margin-top:8px;min-height:14px}
</style></head>
<body><header><h2>DV Agent Harness L5</h2></header>
<main>
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
<div class="note">Real per-run blocking_reason/gate_verdict for the current stage -- not the static explainer below.</div>
<pre id="stageWhy" style="white-space:pre-wrap;font-size:12px;background:#f7f9fc;border:1px solid #e3e9f2;border-radius:6px;padding:8px;margin-top:8px"></pre></div>
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
<div class="note">Real registered protocols and their qualification_status (read from
<code>qualification/protocol_capability_registry.json</code>) -- click a tile to fill the Goal field
below with a start-run goal scoped to that protocol (the exact <code>goal</code> field
POST /api/start already reads).</div>
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
(POST /api/waiver, <code>waiver_store.append_waiver()</code>) -- the real form counterpart to an AI
agent's own fenced <code>dv-harness-evidence:&lt;gate_id&gt;</code> waiver block. This store is not
wired into any gate script's own <code>--waivers</code>/<code>--holes</code>/<code>--coverage</code>
input today (each gate's payload is assembled ad hoc from the agent's evidence block at stage-run
time, per gate's own bespoke schema -- see <code>waiver_store.py</code>'s module docstring); use this
as the durable record of what a human actually approved, and copy its fields into the relevant
evidence block's waiver entry when authoring one. Both <code>approved</code> and non-empty
<code>evidence</code> are required -- a submission missing either is rejected with a 400.</div>
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
<div class="ctrlrow"><label><input type="checkbox" id="waiverApproved" checked> Approved</label>
  <button onclick="doWaiverSubmit()">Submit Waiver</button></div>
<div id="waiverResult" style="font-size:12px;margin-top:4px"></div>
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

// Protocol tiles (Protocols card): a real click target wiring straight into
// the exact field POST /api/start already reads for scope -- doStart() below
// posts {goal: val('goalInput'), ...}, so filling #goalInput here is not a
// new, uncomsumed field, it is the one the backend already consumes.
function selectProtocol(el, name){
  document.getElementById('goalInput').value = 'verify ' + name;
  document.querySelectorAll('#protocoltiles .protoTile').forEach(t=>t.classList.remove('selected'));
  if(el) el.classList.add('selected');
}

async function postJSON(url, body){
  let resp, text, data;
  try{
    resp = await fetch(url, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body||{})});
    text = await resp.text();
    try { data = JSON.parse(text); } catch(e) { data = {raw:text}; }
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
  let body = {gate_id: val('waiverGateId'), item_id: val('waiverItemId'),
              approved: document.getElementById('waiverApproved').checked,
              evidence: val('waiverEvidence')};
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

async function load(){
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
 // stage, not the static generic explainer.
 let d = s.current_stage_detail;
 document.getElementById('stageWhy').textContent = d
   ? `stage: ${d.stage}\nstatus: ${d.status}\nattempts: ${d.attempts}\nblocking_reason: ${d.blocking_reason||'(none)'}\ngate_verdict: ${d.gate_verdict}\ngate_reasons: ${JSON.stringify(d.gate_reasons)}\nhuman_correction: ${JSON.stringify(d.human_correction)}\nhuman_approval: ${JSON.stringify(d.human_approval)}\ntakeover: ${JSON.stringify(d.takeover)}`
   : '(no current stage)';

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

 // Protocols: real registered protocols + qualification_status, each tile a
 // real click target (selectProtocol()) that fills the Goal field POST
 // /api/start actually reads -- not a static reference-only div.
 document.getElementById('protocoltiles').innerHTML = (s.protocol_registry||[]).length
   ? s.protocol_registry.map(p=>
       `<div class="tile protoTile" onclick="selectProtocol(this,'${String(p.name).replace(/'/g,"\\'")}')"><div class="n">${p.name}</div><div class="l">${p.qualification_status}</div></div>`
     ).join('')
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
 await loadCoverageAnalysis();
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
load(); setInterval(load,3000); loadSessions(); loadUserInfo();
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
    }


def _overall_progress(state: dict) -> int:
    """Percent of the 35 canonical stages (len(Stage), NOT len(state['stages'])
    -- an on-disk state.json can predate later Stage enum additions and would
    silently understate the true denominator) that have reached PASS/CLOSED."""
    stages = state.get("stages") or {}
    done = sum(1 for s in Stage if (stages.get(s.value) or {}).get("status") in ("PASS", "CLOSED"))
    total = len(Stage)
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
    fabricating protocols."""
    path = root / ".dv-harness" / "qualification" / "protocol_capability_registry.json"
    data = _read_json_file(path, default=None)
    if not isinstance(data, dict):
        return []
    protocols = data.get("protocols") or {}
    out = []
    for name, rec in protocols.items():
        if not isinstance(rec, dict):
            continue
        out.append({"name": name, "qualification_status": rec.get("qualification_status") or rec.get("status") or "-"})
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


def append_coverage_history_sample(root: Path, percent: float, timestamp: Any = None) -> list:
    """Thin wrapper over coverage_analysis.append_history_sample(), pointed
    at this project's default .dv-harness/coverage/history.json -- the real
    production call a coverage-producing step makes to grow the history GET
    /api/coverage's trend/trend_svg fields read. Called by engine.py's
    DVHarness._append_coverage_history_sample() on every real
    COVERAGE_CLOSURE PASS (Task 6, 2026-08-31 poster-gap-closing round 2),
    with the percent taken from coverage_signoff_verdict_gate's own
    gate-verified coverage_credit_percent evidence field -- never a
    placeholder."""
    from . import coverage_analysis as ca
    return ca.append_history_sample(_default_coverage_history_path(root), percent, timestamp)


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


def _run_key(root: Path) -> str:
    return str(Path(root).resolve())


def _is_running(root: Path) -> bool:
    return _active_runs.get(_run_key(root), False)


def _start_background_run(root: Path, goal: str, loop: bool,
                           adapter_factory: Optional[Callable[[], Any]] = None) -> None:
    """Launches DVHarness(root).loop(goal) (loop=True) or .run_stage(goal)
    (loop=False) on a background daemon thread so the HTTP request returns
    immediately. Raises RuntimeError('ALREADY_RUNNING') instead of starting
    a second concurrent run for the same project_root.

    adapter_factory is a test-only seam: when given, the background
    thread's freshly-constructed DVHarness has its .adapter replaced with
    adapter_factory() before .loop()/.run_stage() is called, so tests can
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
            if loop:
                h.loop(goal)
            else:
                h.run_stage(goal)
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

    class Handler(BaseHTTPRequestHandler):
        def _send(self, data: bytes, content_type: str, status: int = 200):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_json(self, obj: Any, status: int = 200):
            self._send(json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                        "application/json; charset=utf-8", status=status)

        def _read_json_body(self) -> Dict[str, Any]:
            ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip()
            if ctype != "application/json":
                raise ValueError(f"Content-Type must be application/json, got {ctype!r}")
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            raw = self.rfile.read(length) if length > 0 else b""
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
            else:
                self._send(b"not found", "text/plain", status=404)

        # ---- Human Control Plane / setup / start ---------------------------
        def do_POST(self):
            if self.path == "/api/setup":
                self._handle_setup()
            elif self.path == "/api/start":
                self._handle_start()
            elif self.path == "/api/control":
                self._handle_control()
            elif self.path == "/api/config":
                self._handle_config()
            elif self.path == "/api/session/save":
                self._handle_session_save()
            elif self.path == "/api/session/restore":
                self._handle_session_restore()
            elif self.path == "/api/upload":
                self._handle_upload()
            elif self.path == "/api/signoff-export":
                self._handle_signoff_export()
            elif self.path == "/api/waiver":
                self._handle_waiver_submit()
            else:
                self._send_json({"error": "NOT_FOUND", "message": f"no such POST endpoint: {self.path}"},
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

        # POST /api/waiver: {"gate_id": ..., "item_id": ..., "approved": true,
        # "evidence": "..."} -- the real human-facing counterpart to an AI
        # agent's own fenced ```dv-harness-evidence:<gate_id>``` waiver block
        # (see waiver_store.py's module docstring for why this store is a
        # separate, durably-written source of truth rather than a forced
        # integration into gates.run_gate()'s per-invocation tempfile
        # assembly). Calls waiver_store.append_waiver() directly, in this
        # same process -- no subprocess -- same pattern as
        # _handle_signoff_export calling signoff_export.collect_signoff_bundle()
        # directly above.
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
            try:
                _start_background_run(project_root, str(goal), loop, adapter_factory=adapter_factory)
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
                result = _dispatch_control(project_root, body)
            except ValueError as e:
                self._send_json({"error": "BAD_REQUEST", "message": str(e)}, status=400)
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
    print(f"DV Harness Dashboard: http://{host}:{port}")
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-root", default=".")
    a = ap.parse_args()
    serve(Path(a.project_root).resolve())
