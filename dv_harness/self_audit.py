"""Harness self-audit: runs the 23 meta/registry-consistency hard gates
against the HARNESS'S OWN current repo state -- not a per-DUT run's
STAGE_GATES evidence. These 22 scripts have always existed under
tools/verification_flow/ and been registered in
.dv-harness/workflow/hard_gate_registry.json, but nothing ever invoked them;
this module is the missing wire, following the exact pattern the design
investigation confirmed by direct execution (see the investigation's
findings, restated below where each group is defined).

Two groups, confirmed this session by running every one of the 22 scripts
against both a valid and an invalid payload/root:

- ROOT_GATES (6): argparse `--root <dir>`, no JSON payload -- they read the
  repo's own files directly (skills, schemas, registries, test layout).
  Invoked via a small root-scan runner (run_root_gate) since gates.run_gate()
  hardcodes writing a JSON payload to a temp file and passing its path --
  incompatible with a bare `--root` contract.
- JSON_GATES (17): argparse takes a single JSON file via a gate-specific flag
  (NOT a uniform convention -- each gate has its own flag name, verified
  against each script's own argparse this session). Every one is a
  meta/registry/pipeline/platform-wide check, never single-DUT-run evidence.
  Invoked via gates.run_gate() directly -- reusing the exact same
  subprocess/temp-file mechanics STAGE_GATES already uses, no duplicated
  logic.

Real-state sourcing (CLAUDE.md's Evidence Truth Rule: never fabricate data
that could produce a misleading PASS): of the 16 JSON_GATES, only
platform_capability_completeness_gate currently has a real, harness-
maintained file whose shape matches its payload contract
(.dv-harness/workflow/platform_capability_catalog.json, confirmed this
session: PASS, capabilities: 23). Every other JSON_GATES candidate file
under .dv-harness/**/*.json that was checked this session
(protocol_capability_registry.json, protocol_builder_registry.json,
command_schema.json, hard_gate_registry.json, the qualification_suites/*.json
files, ...) uses a materially different schema than what its corresponding
gate script expects -- none can be fed in as-is. Rather than fabricate a
payload that would produce a fake PASS, a gate with no real source reports
NO_SOURCE_DATA honestly (or, with --smoke, SCRIPT_SMOKE_PASS/FAIL against a
constructed representative payload -- a script health-check, not a verdict
on current state, reported under a distinct status so it can never be
misread as a real PASS).

Also confirmed this session by running the 22 scripts against the real repo
right now: agent_skill_binding_gate and hard_gate_registry_audit currently
FAIL for real (skill frontmatter gaps under REAL_ENV_GENERATION/
UNIFIED_REAL_ENV/REAL_PROJECT_GENERATION; several of the registered gates
have no pytest reference). None of this is a bug in this module: it is real,
current self-audit signal, exactly what this feature exists to surface. A
caller should not expect `dv-harness self-audit --all` to report zero FAILs.

UPDATE (2026-08-28, closure pass): gate_manifest_registry_consistency_gate
previously also FAILed here (the 7 gates newly added to STAGE_GATES --
build_failure_triage_gate and 6 siblings -- were registered but not yet
reflected in .dv-harness/workflow/verification_flow_v13.json). That gap is
now closed -- the registry entry was added and this gate now PASSes for
real (confirmed by direct execution, registry_gates: 164). Current totals
(pre-2026-08-28 knowledge-center addition): 5 PASS, 2 FAIL, 15
NO_SOURCE_DATA of 22.

UPDATE (2026-08-28, shared knowledge-center feature): added
knowledge_center_registry_consistency_gate (JSON_GATES, --catalog) --
checks that shared-knowledge-center records (dv_harness/knowledge_center.py
+ tools/knowledge_center/broker.py) declare a manifest-recognized category,
carry a provenance.origin_user, use only the known status vocabulary, and
are never silently ACTIVE past their own revalidate_by expiry. No real
harness-maintained catalog file of shared records exists yet (there is no
running shared knowledge center to source one from until a user actually
runs `dv-harness knowledge setup`), so this gate reports NO_SOURCE_DATA
under --all and SCRIPT_SMOKE_PASS under --smoke, same honest pattern as its
15 pre-existing NO_SOURCE_DATA siblings. Current totals: 5 PASS, 2 FAIL, 16
NO_SOURCE_DATA of 23.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import gates  # reuse gates.run_gate() for the JSON-payload gates

TOOLS_DIR = "tools/verification_flow"

ROOT_GATES = [
    "agent_skill_binding_gate",
    "gate_manifest_registry_consistency_gate",
    "hard_gate_registry_audit",
    "schema_reference_integrity_gate",
    "test_collection_health_gate",
    "workflow_registry_orphan_gate",
]

# gate_id -> (script filename, cli flag) -- verified against each script's
# own argparse this session by direct execution (both PASS- and FAIL-
# producing payloads), NOT a uniform "--evidence" convention.
JSON_GATES: Dict[str, tuple] = {
    "command_catalog_lifecycle_gate":            ("command_catalog_lifecycle_gate.py", "--catalog"),
    "command_catalog_reference_scan_gate":        ("command_catalog_reference_scan_gate.py", "--scan"),
    "control_plane_bidirectional_test_gate":      ("control_plane_bidirectional_test_gate.py", "--coverage"),
    "gate_dependency_consistency":                ("gate_dependency_consistency.py", "--state"),
    "gate_io_contract_consistency_gate":          ("gate_io_contract_consistency_gate.py", "--contracts"),
    "hard_gate_coverage_evidence_gate":           ("hard_gate_coverage_evidence_gate.py", "--coverage"),
    "hard_gate_positive_negative_coverage_gate":  ("hard_gate_positive_negative_coverage_gate.py", "--coverage"),
    "manual_lookup_before_edit_gate":             ("manual_lookup_before_edit_gate.py", "--edit"),
    "one_click_pipeline_gate":                    ("one_click_pipeline_gate.py", "--pipeline"),
    "pipeline_artifact_handoff_gate":             ("pipeline_artifact_handoff_gate.py", "--pipeline"),
    "pipeline_hash_continuity_gate":              ("pipeline_hash_continuity_gate.py", "--pipeline"),
    "platform_capability_completeness_gate":      ("platform_capability_completeness_gate.py", "--catalog"),
    "protocol_family_qualification_gate":         ("protocol_family_qualification_gate.py", "--matrix"),
    "protocol_qualification_ladder_gate":         ("protocol_qualification_ladder_gate.py", "--matrix"),
    "protocol_test_coverage_gate":                ("protocol_test_coverage_gate.py", "--matrix"),
    "system_remote_lsf_coverage_gate":            ("system_remote_lsf_coverage_gate.py", "--flow"),
    "knowledge_center_registry_consistency_gate": ("knowledge_center_registry_consistency_gate.py", "--catalog"),
}

ALL_GATE_IDS = ROOT_GATES + list(JSON_GATES)

_PROTOCOL_FAMILIES = ["PCIe", "Ethernet", "MIPI_CSI2", "MIPI_DSI", "AMBA4",
                       "eDP", "eMMC", "SD_SDIO", "UCIe", "USB"]

_PLATFORM_CAPABILITIES = [
    "INTERACTIVE_INTAKE", "SPEC_RTL_DISCOVERY", "COMMAND_ANALYSIS", "REFERENCE_UVM",
    "DE_BASELINE", "VPLAN", "VERIFICATION_ARCHITECTURE", "OBSERVABILITY",
    "SCOREBOARD_CHECKER_ASSERTION", "TEST_GENERATION", "NEGATIVE_TEST",
    "LOCAL_SIM", "SEMANTIC_TRUE_PASS", "FALSE_PASS_RESISTANCE", "LSF_REGRESSION",
    "REMOTE", "RCA", "DUT_TB_BUG_CLASSIFICATION", "COVERAGE_CLOSURE",
    "SYSTEM_LEVEL", "EXPERT_FEEDBACK", "SIGNOFF", "FEATURE_CONTINUITY",
]

# --- --smoke payloads -------------------------------------------------------
# One constructed, known-good representative payload per JSON_GATES entry --
# proves the SCRIPT still runs and PASSes on well-formed input, never a
# verdict on current harness state (see run_json_gate). Each was verified
# this session via direct subprocess execution (exit 0) against the real
# gate script before being placed here, and a deliberately-broken sibling of
# each was also run to confirm the script's FAIL branch still fires --
# see the self-audit design investigation for the full pass/fail matrix.
SMOKE_PAYLOADS: Dict[str, dict] = {
    "command_catalog_lifecycle_gate": {
        "commands": [{"command_id": "C1", "verification_level": "BLOCK_IP",
                       "category": "build", "destination": "tools/x"}],
        "obsolete_directories": [{"path": "old/", "safe_to_delete": True, "reference_scan_clean": True}],
    },
    "command_catalog_reference_scan_gate": {
        "obsolete_directories": [{"path": "old/", "references": [],
                                   "all_commands_migrated": True, "hash_integrity_verified": True}],
    },
    "control_plane_bidirectional_test_gate": {
        "groups": {
            "SYSTEM_LEVEL": {k: {"positive_test": True, "negative_test": True} for k in
                              ["composition", "traceability", "release_pinning", "change_impact", "deadlock_livelock"]},
            "REMOTE": {k: {"positive_test": True, "negative_test": True} for k in
                       ["supervisory", "state_transition", "action_audit", "replay"]},
            "LSF": {"per_job_monitor": {"positive_test": True, "negative_test": True}},
            "COMMAND_LIFECYCLE": {k: {"positive_test": True, "negative_test": True} for k in
                                   ["catalog", "migration", "reference_scan"]},
        },
    },
    "gate_dependency_consistency": {
        "passed_stages": ["INTAKE_READY", "VPLAN_READY", "ARCHITECTURE_READY", "MECHANISM_READY",
                           "TESTS_READY", "TRACEABILITY_READY", "EXECUTION_EVIDENCE_READY",
                           "COVERAGE_QUALITY_READY", "RCA_READY", "RERUN_READY",
                           "EXPERT_REVIEW_READY", "EXPERIENCE_READY", "PROMOTABLE"],
    },
    "gate_io_contract_consistency_gate": {
        "gates": [{
            "gate_id": "g1", "input_schema": {"type": "object"}, "output_contract": {"status": "str"},
            "required_input_fields": ["a"], "input_schema_fields": ["a", "b"],
            "allowed_statuses": ["PASS", "FAIL"], "emitted_statuses": ["PASS", "FAIL"],
        }],
    },
    "hard_gate_coverage_evidence_gate": {
        "gates": [{"gate_id": "g1", "positive_test_ids": ["t1"], "negative_test_ids": ["t2"],
                    "positive_evidence_hash": "h1", "negative_evidence_hash": "h2",
                    "last_validated_revision": "r1"}],
    },
    "hard_gate_positive_negative_coverage_gate": {
        "gates": [{"gate_id": "g1", "positive_test_ids": ["t1"], "negative_test_ids": ["t2"],
                    "tool_exists": True}],
    },
    "manual_lookup_before_edit_gate": {
        "branch": "branch_b0", "vip_examples_checked": True, "vip_manual_checked": True,
        "vip_source_checked": True, "vip_class_reference_checked": True,
        "vip_evidence_refs": [{"path": "CLAUDE.md", "quote": "Evidence Truth Rule"}],
    },
    "one_click_pipeline_gate": {
        "steps": ["PUSH", "BUILD", "VERIFY", "RUN_WAVE_1", "FSDBREPORT_ANALYSIS"],
        "stop_on_failure": True, "fsdbreport_requires_wave_evidence": True,
    },
    "pipeline_artifact_handoff_gate": {
        "stages": [
            {"name": "PUSH", "inputs": [], "outputs": ["push_out"]},
            {"name": "BUILD", "inputs": ["push_out"], "outputs": ["build_out"]},
            {"name": "VERIFY", "inputs": ["build_out"], "outputs": ["verify_out"]},
            {"name": "RUN_WAVE_1", "inputs": ["verify_out"], "outputs": ["wave_out"]},
            {"name": "FSDBREPORT_ANALYSIS", "inputs": ["wave_out"], "outputs": ["report_out"]},
        ],
    },
    "pipeline_hash_continuity_gate": {
        "stages": [
            {"name": "PUSH", "output_hash": "h1"},
            {"name": "BUILD", "input_hash": "h1", "output_hash": "h2"},
            {"name": "VERIFY", "input_hash": "h2", "output_hash": "h3"},
            {"name": "RUN_WAVE_1", "input_hash": "h3", "output_hash": "h4"},
            {"name": "FSDBREPORT_ANALYSIS", "input_hash": "h4", "output_hash": "h5"},
        ],
    },
    "platform_capability_completeness_gate": {
        "capabilities": [{"capability_id": c, "implemented": True, "test_evidence": "e"}
                          for c in _PLATFORM_CAPABILITIES],
    },
    "protocol_family_qualification_gate": {
        "protocol_families": [
            {"family": f, "profile_available": True, "spec_revision": "r1", "generator_path": "p",
             "qualification_state": "PRODUCTION_QUALIFIED", "qualification_evidence_hash": "h"}
            for f in _PROTOCOL_FAMILIES
        ],
        "new_interface_onboarding_supported": True,
    },
    "protocol_qualification_ladder_gate": {
        "protocols": [
            {"family": f, "qualification_state": "PRODUCTION_QUALIFIED",
             "qualification_history": [
                 {"state": "SMOKE_QUALIFIED", "evidence_hash": "h1"},
                 {"state": "REGRESSION_QUALIFIED", "evidence_hash": "h2"},
                 {"state": "PRODUCTION_QUALIFIED", "evidence_hash": "h3"},
             ]}
            for f in _PROTOCOL_FAMILIES
        ],
    },
    "protocol_test_coverage_gate": {
        "protocols": [
            {"family": f, "testcase_ids": ["t1"], "coverage_ids": ["c1"], "result_evidence_ids": ["r1"]}
            for f in _PROTOCOL_FAMILIES
        ],
    },
    "system_remote_lsf_coverage_gate": {
        "system_level_composition_gate": True, "system_level_traceability_gate": True,
        "system_level_release_pinning_gate": True, "system_level_change_impact_gate": True,
        "system_level_deadlock_livelock_gate": True,
        "remote_control_supervisory_gate": True, "remote_state_transition_gate": True,
        "remote_action_audit_gate": True, "remote_action_replay_gate": True,
        "lsf_per_job_monitor_gate": True,
    },
    "knowledge_center_registry_consistency_gate": {
        "manifest": {"schema_version": 1, "categories": ["usb", "_general"]},
        "records": [
            {"memory_id": "KC-1", "category": "usb", "protocol": "usb", "status": "ACTIVE",
             "written_at": 1.0, "revalidate_by": None,
             "provenance": {"origin_user": "alice", "origin_host": "pc1"}},
        ],
    },
}


# --- Real-state payload sourcing --------------------------------------------
# Each builder returns a real payload read from a harness-maintained file, or
# None if no such file exists yet. Confirmed this session by scanning every
# .dv-harness/**/*.json for a top-level shape matching each JSON_GATES
# contract: only ONE gate has a genuinely matching real source today. Do not
# add a builder for any of the other 15 without pointing at a real,
# harness-maintained artifact -- inventing one defeats the audit (CLAUDE.md
# Evidence Truth Rule).
def _source_platform_capability_completeness_gate(root: Path) -> Optional[dict]:
    f = root / ".dv-harness" / "workflow" / "platform_capability_catalog.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return None


SOURCE_BUILDERS = {
    "platform_capability_completeness_gate": _source_platform_capability_completeness_gate,
    # every other JSON_GATES entry: intentionally absent -- see run_json_gate's
    # NO_SOURCE_DATA branch, and the module docstring above.
}


class SelfAuditResult:
    __slots__ = ("gate_id", "status", "detail", "mode")

    def __init__(self, gate_id: str, status: str, detail: dict, mode: str):
        self.gate_id, self.status, self.detail, self.mode = gate_id, status, detail, mode

    def to_dict(self) -> Dict[str, Any]:
        return {"gate_id": self.gate_id, "status": self.status, "mode": self.mode, "detail": self.detail}


def run_root_gate(root: Path, gate_id: str) -> SelfAuditResult:
    script = root / TOOLS_DIR / f"{gate_id}.py"
    if not script.exists():
        return SelfAuditResult(gate_id, "GATE_TOOL_MISSING", {"tool": str(script)}, "ROOT_SCAN")
    try:
        # TIMEOUT WIDENED 30->100 (2026-09-03, harness-self-test-ci pass): this wrapper's own
        # timeout must exceed test_collection_health_gate.py's internal pytest --collect-only
        # timeout (tools/verification_flow/test_collection_health_gate.py, widened 25->90 in the
        # same pass) or this OUTER timeout always fires first, hard-killing the gate subprocess
        # before its own inner timeout ever gets a chance to report a clean PYTEST_COLLECTION_TIMEOUT
        # JSON result -- confirmed this session: under real concurrent multi-session CPU load on
        # this dev machine, self-audit's test_collection_health_gate FAILed via this exact path
        # even after the inner script's own timeout was already widened. The other 5 ROOT_GATES
        # scripts (registry/schema/skill/workflow scans, no pytest invocation) finish in well under
        # a second even under load, so widening this shared wrapper timeout costs them nothing.
        proc = subprocess.run([sys.executable, str(script), "--root", str(root)],
                               cwd=str(root), capture_output=True, text=True, timeout=100)
    except subprocess.TimeoutExpired:
        return SelfAuditResult(gate_id, "FAIL", {"status": "FAIL", "reason": "GATE_TIMEOUT"}, "ROOT_SCAN")
    try:
        detail = json.loads((proc.stdout or "").strip() or "{}")
    except Exception:
        detail = {"status": "FAIL", "reason": "GATE_OUTPUT_UNPARSEABLE", "raw": (proc.stdout or "")[-500:]}
    return SelfAuditResult(gate_id, "PASS" if proc.returncode == 0 else "FAIL", detail, "ROOT_SCAN")


def run_json_gate(root: Path, gate_id: str, smoke: bool = False) -> SelfAuditResult:
    script_name, flag = JSON_GATES[gate_id]
    if not (root / TOOLS_DIR / script_name).exists():
        return SelfAuditResult(gate_id, "GATE_TOOL_MISSING", {"tool": script_name}, "SOURCED")

    builder = SOURCE_BUILDERS.get(gate_id)
    payload = builder(root) if builder else None
    if payload is not None:
        gr = gates.run_gate(root, script_name, flag, payload)  # reuse gates.py's exact subprocess pattern
        return SelfAuditResult(gate_id, "PASS" if gr.ok else "FAIL", gr.detail, "SOURCED")

    if not smoke:
        return SelfAuditResult(gate_id, "NO_SOURCE_DATA",
            {"reason": "no real harness-state file currently maps to this gate's payload contract",
             "cli_flag": flag}, "SOURCED")

    # --smoke: prove the SCRIPT still runs correctly against a constructed,
    # known-good representative payload. Script health-check, NOT a verdict
    # on current harness state -- reported under a distinct status so it can
    # never be misread as a real PASS.
    smoke_payload = SMOKE_PAYLOADS.get(gate_id)
    if smoke_payload is None:
        return SelfAuditResult(gate_id, "NO_SOURCE_DATA",
            {"reason": "no real harness-state file and no smoke payload defined for this gate",
             "cli_flag": flag}, "SOURCED")
    gr = gates.run_gate(root, script_name, flag, smoke_payload)
    return SelfAuditResult(gate_id, "SCRIPT_SMOKE_PASS" if gr.ok else "SCRIPT_SMOKE_FAIL", gr.detail, "SMOKE")


def run_self_audit(root: Path, gate_ids: Optional[List[str]] = None, smoke: bool = False) -> Dict[str, Any]:
    """Single implementation shared by CLI `dv-harness self-audit` and
    dashboard `GET /api/self-audit`. Deliberately a plain, stateless query
    module (no `h: DVHarness`, no control.json mutation, no events.jsonl
    entry) -- self-audit never changes run state, so it follows the
    regression_reporter.load_jobs/get_job + dashboard._audit_trail precedent
    (module-level function called directly by both callers) rather than
    dv_harness/commands.py's cmd_* pattern, which exists specifically for
    Human Control Plane verbs that mutate state and must be event-logged.
    Same "exactly one implementation, N callers" discipline either way.

    gate_ids: run only these gate ids (repeatable ?gate=x&gate=y on the
    dashboard side, repeatable --gate on the CLI side); omit/None for all 22
    (ALL_GATE_IDS). Unknown ids are reported in "unknown_gate_ids", not run.
    smoke: for a JSON_GATES entry with no real state-file source, run the
    script against a constructed representative payload instead of
    NO_SOURCE_DATA -- see run_json_gate's docstring.
    """
    root = Path(root)
    ids = list(gate_ids) if gate_ids else list(ALL_GATE_IDS)
    unknown = [g for g in ids if g not in ALL_GATE_IDS]
    known = [g for g in ids if g not in unknown]
    results = [
        run_root_gate(root, g) if g in ROOT_GATES else run_json_gate(root, g, smoke=smoke)
        for g in known
    ]

    def count(status):
        return sum(r.status == status for r in results)

    summary = {
        "total": len(results),
        "pass": count("PASS"),
        "fail": count("FAIL"),
        "no_source_data": count("NO_SOURCE_DATA"),
        "tool_missing": count("GATE_TOOL_MISSING"),
        "smoke_pass": count("SCRIPT_SMOKE_PASS"),
        "smoke_fail": count("SCRIPT_SMOKE_FAIL"),
    }
    return {"summary": summary, "unknown_gate_ids": unknown, "gates": [r.to_dict() for r in results]}
