"""dv_harness/golden_flow_readiness.py -- section 47's GOLDEN FLOW READINESS
MATRIX as a real, auto-generated artifact.

THE GAP THIS CLOSES
-------------------
Section 47 mandates that "a complete L5 audit must additionally report" a
twenty-row table with the columns

    Golden Flow Stage | Status | Evidence | Gap | Next-Best-Action

and rules that "the Golden Flow is READY only when required stages are
connected end-to-end with evidence". Every per-domain fact that table
aggregates was already real and queryable in this repo -- state.json's real
per-stage status, gates.STAGE_GATES/effective_stage_gates(), dashboard.py's
coverage/LSF/memory/protocol/failure-attribution readers,
signoff_export.read_signoff_stage_status(), env_manifest's
testplan_correspondence, memory_doctor.check_obsidian() -- but nothing ever
rendered them into the document's row shape. A 2026-09-05 completeness audit
recorded the matrix as NEVER_BUILT as an auto-generated artifact: it existed
only as prose an auditing session was trusted to assemble by hand, which means
two audits of the same project could disagree about the same facts.

WHAT THIS MODULE IS NOT
-----------------------
Stated first, because it is the boundary the whole module lives inside.

  * It DERIVES NOTHING that an existing reader already supplies. Every cell in
    every row is sourced from a named, already-real function (recorded per row
    in `fact_source`, and asserted importable by `assert_fact_sources_resolvable()`).
    Re-implementing "is coverage available" or "did SIGNOFF pass" locally would
    make this module a second, silently-diverging opinion about facts the
    dashboard and the gates already own -- exactly the parallel mechanism this
    project forbids.
  * It WRITES NO GOVERNANCE STATE and RUNS NOTHING. No stage is executed, no
    gate script is invoked, no build or regression is submitted, no state,
    control or approval file is written. Two deliberate consequences of that:
    state.json is read through `dashboard._read_json_file()` rather than
    `storage.StateStore.load()`, which would CREATE a state.json (and a
    .dv-harness/ tree) in a project that has never run -- the same reasoning
    `signoff_export.read_signoff_stage_status()` already records for itself;
    and `loop_contract.observe_all()` (which does go through StateStore) is
    called ONLY when a real state.json already exists, so observing the closure
    loop cannot mint a NOT_STARTED state for a project that has never run. A
    readiness report must not change the readiness it reports. (Disclosed
    precisely: the `dv-harness golden-flow-readiness` WRAPPER still constructs a
    `DVHarness` and appends the usual `CLI_ACCESS` audit event before dispatch,
    exactly as `status`/`explain` do -- that is the CLI's universal behaviour,
    not this report's. Call this module directly, or `python -m
    dv_harness.golden_flow_readiness`, for the untouched-tree guarantee.)
  * It APPROVES NOTHING. A READY verdict is an input to a human's signoff
    decision, never a substitute for one, and this module has no write path to
    any approval record.

WHY THE STATUS VOCABULARY IS BORROWED, NOT MINTED
-------------------------------------------------
Section 47's Status column asks "is this golden-flow stage connected with
evidence", which is the READY/PARTIAL/BLOCKED/UNKNOWN question
`subsystem_discovery` already defines four words for and `system_readiness.py`
already reused one level up. Those same four words are reused again here rather
than minting a fifth set. The per-stage `models.Status` vocabulary is a
DIFFERENT question ("what did the engine last record for this stage") and is
mapped onto the readiness words by `STATUS_TO_READINESS`, whose totality over
`models.Status` is asserted at import time -- a new Status member added later
fails loudly here instead of silently rendering as UNKNOWN.

WHY THE Next-Best-Action COLUMN IS NOT FREE PROSE
--------------------------------------------------
It is produced by the REAL `inference.next_best_action()` through its
`gap_action_catalog` parameter -- the same domain-neutral Gap -> Next-Best-Action
engine `capability_evolution.py` already drives with its own catalog, and the
one the master prompt's section 10 forbids re-implementing. A table keyed on the
row rather than prose written per run means the advice cannot silently differ
between two audits of the same project.

WHY SOME ROWS MAP TO A STAGE WHOSE NAME IS DIFFERENT
-----------------------------------------------------
Section 47's row labels are the document's Golden Flow vocabulary; this engine's
stage ids are `models.Stage`'s. Each mapping is recorded explicitly in the row's
own `basis` string rather than assumed, and the two mappings a reader is most
likely to challenge are called out here:

  * "Verification IR" -> PROJECT_MODEL. Section 33 defines the Verification IR
    as the structured representation carrying verification boundary, protocol/
    interface context and confidence, and explicitly says to ENHANCE an existing
    representation rather than ADD a new one. PROJECT_MODEL's own
    project_model_topology_completeness_gate evidence block is that structure in
    this engine (verification_boundary / vip_topology / blocks / model_confidence
    / dv_readiness). No separate "IR" artifact was invented to satisfy the row.
  * "Verification Contract" -> VERIFICATION_ARCHITECTURE. Section 34's contract
    questions (what checker decides correctness, what coverage proves exercise,
    what evidence proves closure) are what that stage's Monitor/Scoreboard/
    Checker/Assertion/independent-reference-model planning gates already decide.

Rows 17-20 (Dashboard, Claude CLI, Obsidian CLI, Five-Level Memory) are
deliberately NOT stage-backed: the document lists them in the same table because
the Golden Flow depends on them, but they are integration capabilities of the
deployment, not stages a run passes through. Their probes read the real config,
the real adapter resolution and the real vault/store detection instead.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from . import subsystem_discovery as sd
from .models import Stage, Status

SCHEMA_VERSION = "1.0"

#: READY / PARTIAL / BLOCKED / UNKNOWN, reused rather than redeclared -- see the
#: module docstring. Section 47's four words are section SYS-4's own four words.
READY = sd.READY
PARTIAL = sd.PARTIAL
BLOCKED = sd.BLOCKED
UNKNOWN = sd.UNKNOWN
GOLDEN_FLOW_READINESS_CLASSES: tuple = sd.READINESS_CLASSES

#: Worst-wins ordering used by `combine_readiness()`. BLOCKED is worse than
#: UNKNOWN on purpose: "we know this is broken" must not be averaged away by
#: "we do not know about that one".
_SEVERITY = {READY: 0, UNKNOWN: 1, PARTIAL: 2, BLOCKED: 3}

#: Section 47's exact column set, in the document's order. Rendered through
#: `connectivity.render_markdown_table()`, this repo's only parameterized table
#: renderer -- a second hand-rolled `"| " + " | ".join(...)` loop is how a
#: column list drifts out of agreement with the spec it came from.
GOLDEN_FLOW_MATRIX_COLUMNS: tuple = (
    ("row", "Golden Flow Stage"),
    ("status", "Status"),
    ("evidence", "Evidence"),
    ("gap", "Gap"),
    ("next_best_action", "Next-Best-Action"),
)

#: Rendered in any cell whose real source supplied nothing. Never an empty
#: string: "this fact is absent" and "this column was never filled in" must not
#: look alike to a reviewer.
NONE_CELL = "-"


class GoldenFlowReadinessError(ValueError):
    def __init__(self, reason: str, detail: Optional[dict] = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}


# ===========================================================================
# models.Status -> readiness class
# ===========================================================================

#: Total over `models.Status` -- asserted below. A stage the engine has no
#: record for at all is a separate case (UNKNOWN, with "never run" as its gap)
#: and is handled by `_stage_readiness()`, not by this table.
STATUS_TO_READINESS: Dict[str, str] = {
    Status.PASS.value: READY,
    Status.CLOSED.value: READY,
    # A human accepted a known risk here. That is a real, audited decision and
    # NOT evidence the stage is connected end-to-end -- section 47's READY is an
    # evidence claim, so this floors to PARTIAL rather than rounding up.
    Status.ACCEPTED_RISK.value: PARTIAL,
    Status.PARTIAL.value: PARTIAL,
    Status.RUNNING.value: PARTIAL,
    Status.RETRY.value: PARTIAL,
    Status.WAIT_USER.value: PARTIAL,
    Status.FAIL.value: BLOCKED,
    Status.BLOCKED.value: BLOCKED,
    Status.NOT_STARTED.value: UNKNOWN,
}


def assert_status_mapping_total() -> None:
    """Import-time guard: every `models.Status` member has a readiness class.

    Without this, adding a Status member later would make every stage carrying
    it render UNKNOWN -- an honest-looking cell that is actually a bug.
    """
    missing = [s.value for s in Status if s.value not in STATUS_TO_READINESS]
    if missing:
        raise GoldenFlowReadinessError("STATUS_READINESS_MAPPING_INCOMPLETE", {
            "missing": missing,
            "known": sorted(STATUS_TO_READINESS),
            "hint": "add the new models.Status member to STATUS_TO_READINESS"})
    unknown = [k for k in STATUS_TO_READINESS if k not in {s.value for s in Status}]
    if unknown:
        raise GoldenFlowReadinessError("STATUS_READINESS_MAPPING_HAS_UNKNOWN_STATUS", {
            "unknown": unknown})


assert_status_mapping_total()


def combine_readiness(values) -> str:
    """Worst-wins over a set of readiness classes, with two deliberate rules:

      * an empty input is UNKNOWN (nothing was measured), never READY;
      * a mix of READY and UNKNOWN is PARTIAL, not UNKNOWN -- half a row being
        connected with evidence is exactly what PARTIAL means, and reporting it
        as UNKNOWN would hide real progress.
    """
    vals = [v for v in (values or ()) if v]
    if not vals:
        return UNKNOWN
    for v in vals:
        if v not in _SEVERITY:
            raise GoldenFlowReadinessError("UNKNOWN_READINESS_CLASS", {
                "value": v, "legal_values": list(GOLDEN_FLOW_READINESS_CLASSES)})
    if all(v == READY for v in vals):
        return READY
    if any(v == BLOCKED for v in vals):
        return BLOCKED
    if all(v == UNKNOWN for v in vals):
        return UNKNOWN
    return PARTIAL


# ===========================================================================
# Row declarations -- section 47's twenty rows, in the document's order
# ===========================================================================

@dataclass(frozen=True)
class GoldenFlowRowSpec:
    """One declared row of section 47's matrix.

    `label` is the document's own wording, character for character -- the
    import-time check below is what stops a later edit from quietly renaming a
    row the specification names. `harness_stages` are real `models.Stage`
    values (validated at import) and `fact_source` names the already-real
    reader the probe calls, so `assert_fact_sources_resolvable()` can prove
    every row is backed by code that still exists.
    """
    row_id: str
    label: str
    harness_stages: Tuple[str, ...]
    fact_source: Tuple[str, ...]
    basis: str


ROWS: Tuple[GoldenFlowRowSpec, ...] = (
    GoldenFlowRowSpec(
        "spec_in", "Spec In", (Stage.INTAKE.value,),
        ("dv_harness.dashboard._read_json_file", "dv_harness.dashboard._uploaded_files",
         "dv_harness.gates.effective_stage_gates"),
        "INTAKE is the stage that takes spec/RTL/command.txt/reference/DE-local-sim "
        "input in; the real uploaded-document inventory is the same one GET /api/state "
        "reports."),
    GoldenFlowRowSpec(
        "requirement_extraction", "Requirement Extraction",
        (Stage.REQUIREMENTS_TRACEABILITY.value,),
        ("dv_harness.dashboard._read_json_file", "dv_harness.gates.effective_stage_gates"),
        "REQUIREMENTS_TRACEABILITY's own prompt is 'Requirement Extraction + "
        "Applicability/Waiver', gated by spec_to_vplan_requirement_quality_gate."),
    GoldenFlowRowSpec(
        "verification_ir", "Verification IR", (Stage.PROJECT_MODEL.value,),
        ("dv_harness.dashboard._read_json_file", "dv_harness.gates.extract_evidence_blocks"),
        "Section 33's IR fields (boundary, protocol/interface context, confidence) are "
        "PROJECT_MODEL's project_model_topology_completeness_gate evidence block; section "
        "33 says ENHANCE an existing representation rather than ADD a new one."),
    GoldenFlowRowSpec(
        "verification_contract", "Verification Contract",
        (Stage.VERIFICATION_ARCHITECTURE.value,),
        ("dv_harness.dashboard._read_json_file", "dv_harness.gates.effective_stage_gates"),
        "Section 34's contract questions (which deterministic checker decides "
        "correctness, what coverage proves exercise) are what VERIFICATION_ARCHITECTURE's "
        "checker/scoreboard/assertion/observability gates already decide."),
    GoldenFlowRowSpec(
        "vplan_traceability", "vPlan / Traceability",
        (Stage.VPLAN.value,),
        ("dv_harness.dashboard._read_json_file", "dv_harness.env_manifest.default_manifest_path",
         "dv_harness.env_manifest.load_env_manifest"),
        "The VPLAN stage plus env.manifest.json's testplan_correspondence -- the real "
        "testlist/vPlan/coverage-model three-way join, which is the only artifact that "
        "can show a vPlan item claiming coverage from a test no regression runs."),
    GoldenFlowRowSpec(
        "protocol_topology_discovery", "Protocol/Topology Discovery",
        (Stage.PROTOCOL_CAPABILITY.value, Stage.ARCH_DISCOVERY.value),
        ("dv_harness.dashboard._read_json_file", "dv_harness.dashboard._protocol_registry"),
        "PROTOCOL_CAPABILITY (protocol side) and ARCH_DISCOVERY (RTL-first topology "
        "side), plus the real protocol_capability_registry.json rows GET /api/state "
        "already reads."),
    GoldenFlowRowSpec(
        "vip_uvm_generation", "VIP/UVM Generation", (Stage.IMPLEMENT.value,),
        ("dv_harness.dashboard._read_json_file", "dv_harness.dashboard._protocol_registry"),
        "IMPLEMENT is where monitors/checkers/tests are actually generated; each "
        "protocol's capability_status says whether anything protocol-SPECIFIC exists or "
        "only the protocol-agnostic skeleton."),
    GoldenFlowRowSpec(
        "single_test_proof", "Single-Test Proof",
        (Stage.BUILD.value, Stage.VERIFY.value),
        ("dv_harness.dashboard._read_json_file",),
        "A single-test proof is BUILD (it compiles) AND VERIFY (one test really passed "
        "with a command.txt<->sim.log semantic check); either alone is not the proof."),
    GoldenFlowRowSpec(
        "lsf_regression", "LSF Regression",
        (Stage.REGRESSION.value,),
        ("dv_harness.dashboard._read_json_file", "dv_harness.regression_reporter.load_jobs",
         "dv_harness.dashboard._lsf_summary"),
        "The REGRESSION stage plus the real per-job records GET /api/lsf summarises -- "
        "LSF DONE is not DV PASS, so the row reads dv_analysis_status, not lsf_status."),
    GoldenFlowRowSpec(
        "failure_triage", "Failure Triage",
        (Stage.FAILURE_RECOVERY.value,),
        ("dv_harness.dashboard._read_json_file", "dv_harness.dashboard._failure_attribution"),
        "FAILURE_RECOVERY plus the real DUT_BUG/TB_BUG attribution the dashboard "
        "recomputes from boundary_trace (never the agent's own claimed classification)."),
    GoldenFlowRowSpec(
        "coverage_collection", "Coverage Collection", (),
        ("dv_harness.dashboard._read_coverage_state",),
        "Whether real coverage data exists at all, read through the same "
        "parse_coverage_summary() path GET /api/coverage uses. Not stage-backed: a "
        "COVERAGE_CLOSURE PASS with no summary file on disk is not collected coverage."),
    GoldenFlowRowSpec(
        "coverage_hole_analysis", "Coverage Hole Analysis", (),
        ("dv_harness.dashboard._read_coverage_state", "dv_harness.coverage_analysis.identify_holes"),
        "The real identify_holes() result over that same parsed summary. An empty hole "
        "list with coverage present is READY (analysis ran and found nothing), which is "
        "why this cannot be inferred from the collection row."),
    GoldenFlowRowSpec(
        "next_best_test", "Next-Best-Test", (),
        ("dv_harness.coverage_analysis.classify_coverage_hole",),
        "The real per-hole classifier (MISSING_TEST / INSUFFICIENT_CONSTRAINT / "
        "UNREACHABLE_STIMULUS / INSUFFICIENT_SEED_ATTEMPTS -> recommended_action). "
        "Read-only: it classifies holes, it never generates or runs a test."),
    GoldenFlowRowSpec(
        "coverage_closure_loop", "Coverage Closure Loop",
        (Stage.COVERAGE_CLOSURE.value,),
        ("dv_harness.dashboard._read_json_file", "dv_harness.loop_contract.observe_all"),
        "COVERAGE_CLOSURE's stage record plus the real verification_closure LoopState "
        "loop_contract.observe_all() derives -- the loop's own observer, not a second "
        "opinion about whether the loop is turning."),
    GoldenFlowRowSpec(
        "verification_closure_100", "100% Verification Closure",
        (Stage.REQUIREMENT_CLOSURE.value,),
        ("dv_harness.dashboard._read_json_file", "dv_harness.dashboard._coverage_credit",
         "dv_harness.dashboard._qualified_conclusion"),
        "REQUIREMENT_CLOSURE plus the real recorded coverage_credit_percent and the "
        "persisted qualified_conclusion. Section 56: 100% closure never means 100% "
        "autonomous production modification."),
    GoldenFlowRowSpec(
        "signoff_evidence", "Signoff Evidence", (Stage.SIGNOFF.value,),
        ("dv_harness.signoff_export.read_signoff_stage_status",),
        "signoff_export's own reader, which is what the real bundle collector consults "
        "-- not a second reading of the same stage record."),
    GoldenFlowRowSpec(
        "dashboard", "Dashboard", (),
        ("dv_harness.dashboard.serve", "dv_harness.dashboard_auth.session_file"),
        "Whether the real dashboard server and its auth token mechanism are present in "
        "this deployment. Deployment capability, not a stage."),
    GoldenFlowRowSpec(
        "claude_cli_integration", "Claude CLI Integration", (),
        ("dv_harness.config.load_config", "dv_harness.adapters.cli.ClaudeCLIAdapter._resolve_command"),
        "The configured adapter plus the adapter's OWN PATHEXT-aware command resolution "
        "-- the same resolution a real run-stage would perform, so this row cannot claim "
        "an executable the engine would then fail to launch."),
    GoldenFlowRowSpec(
        "obsidian_cli_integration", "Obsidian CLI Integration", (),
        ("dv_harness.memory_doctor.check_obsidian",),
        "memory_doctor's real detection, including its own recorded finding that an "
        "absent Obsidian CLI is an expected permanent state with the filesystem adapter "
        "as the always-available write path."),
    GoldenFlowRowSpec(
        "five_level_memory", "Five-Level Memory", (),
        ("dv_harness.dashboard._read_memory_center_state",
         "dv_harness.dashboard._locally_stored_memory_levels"),
        "The real per-tier record counts GET /api/memory reports over "
        "memory.MEMORY_LEVELS, with the locally-stored tier set derived from "
        "memory_router's own dispatch tables."),
)


def row_ids() -> List[str]:
    return [r.row_id for r in ROWS]


def row_labels() -> List[str]:
    return [r.label for r in ROWS]


#: Section 47 prints twenty rows. Transcribed once here so the import-time check
#: below compares the declarations against the specification's own list rather
#: than against itself -- the audit that preceded this module found a
#: hand-assembled matrix with rows silently missing, which is precisely the
#: mistake a list that validates only its own length makes.
SECTION_47_ROW_LABELS: tuple = (
    "Spec In", "Requirement Extraction", "Verification IR", "Verification Contract",
    "vPlan / Traceability", "Protocol/Topology Discovery", "VIP/UVM Generation",
    "Single-Test Proof", "LSF Regression", "Failure Triage", "Coverage Collection",
    "Coverage Hole Analysis", "Next-Best-Test", "Coverage Closure Loop",
    "100% Verification Closure", "Signoff Evidence", "Dashboard",
    "Claude CLI Integration", "Obsidian CLI Integration", "Five-Level Memory",
)


def _assert_rows_match_section_47() -> None:
    declared = tuple(r.label for r in ROWS)
    if declared != SECTION_47_ROW_LABELS:
        raise GoldenFlowReadinessError("SECTION_47_ROW_SET_CHANGED", {
            "declared": list(declared),
            "specification": list(SECTION_47_ROW_LABELS),
            "missing": [l for l in SECTION_47_ROW_LABELS if l not in declared],
            "unexpected": [l for l in declared if l not in SECTION_47_ROW_LABELS]})
    ids = [r.row_id for r in ROWS]
    if len(set(ids)) != len(ids):
        raise GoldenFlowReadinessError("DUPLICATE_ROW_ID", {"row_ids": ids})


def _assert_declared_stages_are_real() -> None:
    known = {s.value for s in Stage}
    bad = sorted({s for r in ROWS for s in r.harness_stages if s not in known})
    if bad:
        raise GoldenFlowReadinessError("UNKNOWN_HARNESS_STAGE_IN_ROW_SPEC", {
            "unknown_stages": bad, "known_stages": sorted(known)})


_assert_rows_match_section_47()
_assert_declared_stages_are_real()


# ===========================================================================
# Gap -> Next-Best-Action catalog (driven through inference.next_best_action)
# ===========================================================================

#: The catalog shape `inference.next_best_action()` documents. Keyed by row_id
#: so the advice for a row is one registered string rather than prose written
#: per run -- see the module docstring for why this is not free text.
GOLDEN_FLOW_GAP_ACTION_CATALOG: Dict[str, Any] = {
    "source": "golden_flow_readiness_row",
    "fallback": (
        "no next action is registered for '{gap}' -- name the missing evidence and the "
        "real command that would produce it before treating this row as closed"
    ),
    "actions": {
        "spec_in": (
            "run `dv-harness run-stage INTAKE`; if it is already PASS, the missing half "
            "is real input -- upload the spec/RTL/command.txt/reference documents the "
            "intake gates ask for"),
        "requirement_extraction": (
            "run `dv-harness run-stage REQUIREMENTS_TRACEABILITY` and resolve the "
            "spec_to_vplan_requirement_quality_gate findings; a DUT-unsupported "
            "requirement needs a waiver with design_evidence, never deletion"),
        "verification_ir": (
            "run `dv-harness run-stage PROJECT_MODEL` so the "
            "project_model_topology_completeness_gate block (verification_boundary, "
            "vip_topology, blocks, model_confidence, dv_readiness) actually exists"),
        "verification_contract": (
            "run `dv-harness run-stage VERIFICATION_ARCHITECTURE`; the contract is not "
            "complete until a deterministic checker -- not an LLM-generated expectation "
            "-- decides correctness for each requirement"),
        "vplan_traceability": (
            "run `dv-harness run-stage VPLAN`, then `dv-harness env-manifest generate "
            "--testplan-sources <file>` so the testlist/vPlan/coverage-model join is "
            "real; `dv-harness vplan-export` writes the reviewable workbook"),
        "protocol_topology_discovery": (
            "run `dv-harness run-stage ARCH_DISCOVERY` and `dv-harness run-stage "
            "PROTOCOL_CAPABILITY`; a registry row saying GENERIC_SKELETON_ONLY means no "
            "protocol-specific model exists yet, not that discovery failed"),
        "vip_uvm_generation": (
            "run `dv-harness run-stage IMPLEMENT`; generation must be based on real "
            "VIP/reference/RTL evidence (AT-22), so close the protocol capability row "
            "first if it reports GENERIC_SKELETON_ONLY"),
        "single_test_proof": (
            "run `dv-harness run-stage BUILD` then `dv-harness run-stage VERIFY`; a "
            "build that compiles is not a proof, and LSF DONE is not DV PASS"),
        "lsf_regression": (
            "run `dv-harness run-stage REGRESSION` (or `dv-harness lsf-submit`) and "
            "reconcile with `dv-harness lsf-reconcile`; jobs whose dv_analysis_status is "
            "still empty are unproven, not passing"),
        "failure_triage": (
            "run `dv-harness run-stage FAILURE_RECOVERY` and supply a real boundary_trace "
            "-- the DUT_BUG/TB_BUG verdict is recomputed from it, so a stated "
            "classification alone closes nothing"),
        "coverage_collection": (
            "produce real coverage data at .dv-harness/coverage/summary.json (the path "
            "GET /api/coverage reads); no summary file is the honest pre-first-run "
            "state, never 0%"),
        "coverage_hole_analysis": (
            "with a real summary present this runs automatically -- if it reports an "
            "error, fix the malformed coverage summary rather than the analysis"),
        "next_best_test": (
            "classify each hole through `dv-harness run-stage COVERAGE_CLOSURE`'s "
            "coverage_hole_regeneration_gate evidence; a bin with too few seed attempts "
            "gets more seeds, not a new testcase"),
        "coverage_closure_loop": (
            "run `dv-harness run-stage COVERAGE_CLOSURE` and check `dv-harness "
            "loop-contract convergence` -- a PLATEAU verdict means the loop is turning "
            "without converging and needs the unreachable-bin investigation"),
        "verification_closure_100": (
            "run `dv-harness run-stage REQUIREMENT_CLOSURE`; closure needs the recorded "
            "coverage_credit_percent and a qualified_conclusion, not a stage PASS alone"),
        "signoff_evidence": (
            "run `dv-harness run-stage SIGNOFF` (human approval required) and then "
            "`dv-harness signoff-export` to bundle the evidence"),
        "dashboard": (
            "start it with `dv-harness dashboard`; the auth token is created on first "
            "serve, so an absent token is expected before the first run"),
        "claude_cli_integration": (
            "install the Claude CLI and/or set claude.command in .dv-harness/config.json "
            "to a real executable -- the engine resolves it exactly the way this row does"),
        "obsidian_cli_integration": (
            "none required: the filesystem adapter is the real, always-available write "
            "path and an absent Obsidian CLI is an expected permanent state (see "
            "`dv-harness memory doctor`)"),
        "five_level_memory": (
            "write real records through the engine or `dv-harness memory add`; an empty "
            "store is the honest pre-first-run state and `dv-harness memory doctor` "
            "reports whether the store/vault is healthy"),
    },
}


def _next_best_actions(root: Path, gaps: List[str]) -> Dict[str, str]:
    """row_id -> suggested action, via the REAL inference engine.

    `protocol` is None because this caller is not protocol-scoped; the catalog
    branch of `next_best_action()` never reaches the protocol registry.
    """
    if not gaps:
        return {}
    from .inference import next_best_action
    results = next_best_action(None, gaps, root,
                               gap_action_catalog=GOLDEN_FLOW_GAP_ACTION_CATALOG)
    return {r["gap"]: r["suggested_action"] for r in results}


# ===========================================================================
# Fact gathering -- every read below goes through an already-real reader
# ===========================================================================

@dataclass
class _Facts:
    """Everything the probes read, gathered once per report.

    Each field is either the real reader's own return value or None when that
    reader reported absence. Nothing here is computed from anything else.
    """
    root: Path
    cfg: Dict[str, Any]
    state: Optional[Dict[str, Any]]
    stage_records: Dict[str, Dict[str, Any]]


def _gather_facts(root: Path, cfg: Optional[Dict[str, Any]] = None) -> _Facts:
    from .dashboard import _read_json_file
    if cfg is None:
        from .config import DEFAULT_CONFIG, load_config
        # load_config() MATERIALIZES a default config.json when none exists.
        # For a project that has never run, take the same deep copy of the same
        # DEFAULT_CONFIG that branch returns, minus the write -- the merge logic
        # is not reimplemented here, it is simply not needed when there is no
        # file to merge.
        if (Path(root) / ".dv-harness" / "config.json").exists():
            cfg = load_config(root)
        else:
            import json as _json
            cfg = _json.loads(_json.dumps(DEFAULT_CONFIG))
    # Read-only: _read_json_file() returns None for an absent file, where
    # StateStore.load() would CREATE one. See the module docstring.
    state = _read_json_file(root / ".dv-harness" / "state.json")
    stage_records = {}
    if isinstance(state, dict):
        for sid, rec in (state.get("stages") or {}).items():
            if isinstance(rec, dict):
                stage_records[sid] = rec
    return _Facts(root=Path(root), cfg=cfg, state=state, stage_records=stage_records)


def _stage_readiness(facts: _Facts, stage: str) -> Tuple[str, str, str]:
    """(readiness, evidence_fragment, gap_fragment) for one real harness stage."""
    rec = facts.stage_records.get(stage)
    if rec is None:
        return UNKNOWN, f"{stage}=NO_RECORD", f"{stage} has never run"
    status = rec.get("status") or Status.NOT_STARTED.value
    readiness = STATUS_TO_READINESS.get(status, UNKNOWN)
    evidence = f"{stage}={status}"
    gap = ""
    if readiness != READY:
        reason = (rec.get("blocking_reason") or "").strip()
        gap = f"{stage} is {status}" + (f": {reason}" if reason else "")
    return readiness, evidence, gap


def _stage_gate_count(facts: _Facts, stage: str) -> int:
    """How many real gates back this stage, via gates.effective_stage_gates().

    A project with no `.dv-harness/` at all is read from `gates.STAGE_GATES`
    directly instead: `effective_stage_gates()` reads the self-tuning overlay
    through `self_tuning._dir()`, which mkdirs, and there cannot BE an overlay
    in a project that has never been initialized -- so the baseline IS the
    effective set there, and this stays read-only for an uninitialized tree.

    Best-effort either way: "how many gates" is supporting evidence for the
    row, never the row's verdict, so a failure counts 0 rather than raising.
    """
    try:
        from .gates import STAGE_GATES, effective_stage_gates
        if not (facts.root / ".dv-harness").exists():
            return len(STAGE_GATES.get(stage, []))
        return len(effective_stage_gates(stage, facts.root) or [])
    except Exception:
        return 0


def _stages_verdict(facts: _Facts, spec: GoldenFlowRowSpec) -> Tuple[str, List[str], List[str]]:
    readiness, evidence, gaps = [], [], []
    for stage in spec.harness_stages:
        r, e, g = _stage_readiness(facts, stage)
        readiness.append(r)
        evidence.append(e)
        if g:
            gaps.append(g)
    return combine_readiness(readiness), evidence, gaps


def _evidence_block(facts: _Facts, stage: str, gate_id: str) -> Optional[dict]:
    """One gate's evidence block out of a stage's own recorded response --
    the same extraction dashboard.py's own readers use."""
    from .gates import extract_evidence_blocks
    rec = facts.stage_records.get(stage) or {}
    try:
        blocks = extract_evidence_blocks(rec.get("last_message") or "")
    except Exception:
        return None
    payload = blocks.get(gate_id)
    return payload if isinstance(payload, dict) else None


# ===========================================================================
# Per-row probes
# ===========================================================================
#
# Contract, held by every probe below:
#   * returns {"status", "evidence", "gap"};
#   * reads only through the readers named in the row's own `fact_source`;
#   * NEVER raises for a project that has not run -- absence is a verdict
#     (UNKNOWN plus a gap that names what is absent), not an error. A reader
#     that itself fails is reported in the gap cell, because "the coverage
#     summary is malformed" is what the reviewer needs to see.

def _probe_spec_in(facts: _Facts, spec: GoldenFlowRowSpec) -> Dict[str, str]:
    from .dashboard import _uploaded_files
    verdict, evidence, gaps = _stages_verdict(facts, spec)
    try:
        uploads = _uploaded_files(facts.root)
        n = sum(len(v or []) for v in (uploads or {}).values())
    except Exception as e:
        n, uploads = 0, None
        gaps.append(f"upload inventory unreadable: {e}")
    gates = _stage_gate_count(facts, Stage.INTAKE.value)
    evidence.append(f"{n} uploaded document(s)")
    if gates:
        evidence.append(f"{gates} INTAKE gate(s)")
    if uploads is not None and n == 0:
        gaps.append("no spec/RTL/reference document has been supplied")
        verdict = combine_readiness([verdict, UNKNOWN])
    return {"status": verdict, "evidence": "; ".join(evidence), "gap": "; ".join(gaps)}


def _probe_stage_only(facts: _Facts, spec: GoldenFlowRowSpec) -> Dict[str, str]:
    """The plain stage-backed row: REQUIREMENT extraction, contract, single-test
    proof. Gate count is included as supporting evidence so a reviewer can see
    the verdict rests on real gates rather than a status string alone."""
    verdict, evidence, gaps = _stages_verdict(facts, spec)
    total_gates = sum(_stage_gate_count(facts, s) for s in spec.harness_stages)
    if total_gates:
        evidence.append(f"{total_gates} gate(s)")
    return {"status": verdict, "evidence": "; ".join(evidence), "gap": "; ".join(gaps)}


def _probe_verification_ir(facts: _Facts, spec: GoldenFlowRowSpec) -> Dict[str, str]:
    verdict, evidence, gaps = _stages_verdict(facts, spec)
    block = _evidence_block(facts, Stage.PROJECT_MODEL.value,
                            "project_model_topology_completeness_gate")
    if block is None:
        gaps.append("no project_model_topology_completeness_gate evidence block recorded "
                    "(section 33's IR fields have no home yet)")
        verdict = combine_readiness([verdict, UNKNOWN])
    else:
        present = [k for k in ("verification_boundary", "vip_topology", "blocks",
                               "model_confidence", "dv_readiness") if block.get(k)]
        evidence.append(f"IR fields present: {', '.join(present) or 'none'}")
        if len(present) < 5:
            missing = [k for k in ("verification_boundary", "vip_topology", "blocks",
                                   "model_confidence", "dv_readiness") if not block.get(k)]
            gaps.append("IR fields absent: " + ", ".join(missing))
            verdict = combine_readiness([verdict, PARTIAL])
    return {"status": verdict, "evidence": "; ".join(evidence), "gap": "; ".join(gaps)}


def _probe_vplan_traceability(facts: _Facts, spec: GoldenFlowRowSpec) -> Dict[str, str]:
    from . import env_manifest as em
    verdict, evidence, gaps = _stages_verdict(facts, spec)
    corr = None
    path = None
    try:
        path = em.default_manifest_path(facts.root)
        if path is not None and Path(path).exists():
            manifest = em.load_env_manifest(path)
            corr = ((manifest.get("env_topology") or {}).get("testplan_correspondence")
                    if isinstance(manifest, dict) else None)
    except Exception as e:
        gaps.append(f"env.manifest.json unreadable: {e}")
    if not isinstance(corr, dict):
        evidence.append("testplan_correspondence=NOT_AVAILABLE")
        gaps.append("no testlist/vPlan/coverage-model correspondence has been built")
        verdict = combine_readiness([verdict, UNKNOWN])
    else:
        summary = corr.get("summary") or {}
        status = corr.get("status") or "UNKNOWN"
        evidence.append(
            f"testplan_correspondence={status} "
            f"(linked={summary.get('linked_count', 0)}, broken={summary.get('broken_count', 0)}, "
            f"unclaimed={summary.get('unclaimed_count', 0)})")
        if status == "NOT_AVAILABLE":
            gaps.append(str(corr.get("reason") or "correspondence not available"))
            verdict = combine_readiness([verdict, UNKNOWN])
        elif summary.get("broken_count") or summary.get("unclaimed_count"):
            gaps.append(f"{summary.get('broken_count', 0)} broken and "
                        f"{summary.get('unclaimed_count', 0)} unclaimed vPlan item(s)")
            verdict = combine_readiness([verdict, PARTIAL])
    return {"status": verdict, "evidence": "; ".join(evidence), "gap": "; ".join(gaps)}


def _probe_protocol_topology(facts: _Facts, spec: GoldenFlowRowSpec) -> Dict[str, str]:
    from .dashboard import _protocol_registry
    verdict, evidence, gaps = _stages_verdict(facts, spec)
    try:
        protocols = _protocol_registry(facts.root)
    except Exception as e:
        protocols = []
        gaps.append(f"protocol registry unreadable: {e}")
    evidence.append(f"{len(protocols)} protocol(s) registered")
    if not protocols:
        gaps.append("no protocol is registered in protocol_capability_registry.json")
        verdict = combine_readiness([verdict, UNKNOWN])
    return {"status": verdict, "evidence": "; ".join(evidence), "gap": "; ".join(gaps)}


def _probe_vip_uvm_generation(facts: _Facts, spec: GoldenFlowRowSpec) -> Dict[str, str]:
    from .dashboard import _protocol_registry
    from . import protocol_capability as pc
    verdict, evidence, gaps = _stages_verdict(facts, spec)
    try:
        protocols = _protocol_registry(facts.root)
    except Exception as e:
        protocols = []
        gaps.append(f"protocol registry unreadable: {e}")
    skeleton_only = [p["name"] for p in protocols
                     if p.get("capability_status") == pc.STATUS_GENERIC_SKELETON_ONLY]
    evidence.append(f"{len(protocols) - len(skeleton_only)}/{len(protocols)} protocol(s) with a "
                    f"protocol-specific model")
    if skeleton_only:
        gaps.append("only the protocol-agnostic skeleton exists for: "
                    + ", ".join(sorted(skeleton_only)))
        verdict = combine_readiness([verdict, PARTIAL])
    return {"status": verdict, "evidence": "; ".join(evidence), "gap": "; ".join(gaps)}


def _probe_lsf_regression(facts: _Facts, spec: GoldenFlowRowSpec) -> Dict[str, str]:
    from .dashboard import _lsf_summary
    from .regression_reporter import load_jobs
    verdict, evidence, gaps = _stages_verdict(facts, spec)
    try:
        jobs = load_jobs(facts.root)
        summary = _lsf_summary(jobs)
    except Exception as e:
        summary = None
        gaps.append(f"LSF job records unreadable: {e}")
    if not summary or not summary.get("total"):
        evidence.append("0 LSF job record(s)")
        gaps.append("no regression job has been recorded")
        verdict = combine_readiness([verdict, UNKNOWN])
    else:
        evidence.append(f"{summary['total']} job(s): "
                        f"{summary.get('pass_confirmed', 0)} DV-PASS, "
                        f"{summary.get('fail_confirmed', 0)} DV-FAIL, "
                        f"{summary.get('early_kill', 0)} early-kill")
        unproven = summary["total"] - summary.get("pass_confirmed", 0) - summary.get("fail_confirmed", 0)
        if summary.get("fail_confirmed"):
            gaps.append(f"{summary['fail_confirmed']} job(s) confirmed FAIL by DV analysis")
            verdict = combine_readiness([verdict, BLOCKED])
        if unproven > 0:
            gaps.append(f"{unproven} job(s) have no dv_analysis_status -- LSF DONE is not DV PASS")
            verdict = combine_readiness([verdict, PARTIAL])
    return {"status": verdict, "evidence": "; ".join(evidence), "gap": "; ".join(gaps)}


def _probe_failure_triage(facts: _Facts, spec: GoldenFlowRowSpec) -> Dict[str, str]:
    from .dashboard import _failure_attribution
    verdict, evidence, gaps = _stages_verdict(facts, spec)
    try:
        attribution = _failure_attribution(facts.root)
    except Exception as e:
        attribution = None
        gaps.append(f"failure attribution unreadable: {e}")
    if not attribution:
        evidence.append("no failure_attribution evidence recorded")
        # Not a gap on its own: a project with no failure to triage is not
        # blocked by the absence of a triage record. The stage verdict already
        # says whether FAILURE_RECOVERY ever ran.
    else:
        evidence.append(f"attribution={attribution.get('verdict')}")
        if attribution.get("verdict") == "UNKNOWN":
            gaps.append("boundary_trace does not identify a first bad event, so neither "
                        "DUT_BUG nor TB_BUG is established")
            verdict = combine_readiness([verdict, PARTIAL])
    return {"status": verdict, "evidence": "; ".join(evidence), "gap": "; ".join(gaps)}


def _coverage_state(facts: _Facts) -> Dict[str, Any]:
    from .dashboard import _read_coverage_state
    return _read_coverage_state(facts.root)


def _probe_coverage_collection(facts: _Facts, spec: GoldenFlowRowSpec) -> Dict[str, str]:
    try:
        cov = _coverage_state(facts)
    except Exception as e:
        return {"status": UNKNOWN, "evidence": "coverage state unreadable",
                "gap": f"coverage reader failed: {e}"}
    if not cov.get("available"):
        return {"status": UNKNOWN, "evidence": f"no summary at {cov.get('summary_path')}",
                "gap": "no real coverage summary has been produced"}
    if cov.get("error"):
        return {"status": BLOCKED,
                "evidence": f"summary at {cov.get('summary_path')}",
                "gap": f"coverage summary is malformed: {cov['error'].get('reason')}"}
    cats = cov.get("categories") or []
    return {"status": READY if cats else PARTIAL,
            "evidence": f"{len(cats)} coverage category/categories parsed",
            "gap": "" if cats else "coverage summary parsed but holds no category"}


def _probe_coverage_hole_analysis(facts: _Facts, spec: GoldenFlowRowSpec) -> Dict[str, str]:
    try:
        cov = _coverage_state(facts)
    except Exception as e:
        return {"status": UNKNOWN, "evidence": "coverage state unreadable",
                "gap": f"coverage reader failed: {e}"}
    if not cov.get("available") or cov.get("error"):
        return {"status": UNKNOWN, "evidence": "no parsed coverage to analyse",
                "gap": "hole analysis needs a real, parseable coverage summary first"}
    holes = cov.get("holes") or []
    if not holes:
        return {"status": READY,
                "evidence": "identify_holes() ran and found no category below 100%",
                "gap": ""}
    worst = holes[0]
    return {"status": PARTIAL,
            "evidence": f"{len(holes)} hole(s); worst {worst.get('name')} at "
                        f"{worst.get('percent')}% ({worst.get('bins_missing')} bins missing)",
            "gap": f"{len(holes)} coverage category/categories below 100%"}


def _probe_next_best_test(facts: _Facts, spec: GoldenFlowRowSpec) -> Dict[str, str]:
    from . import coverage_analysis as ca
    try:
        cov = _coverage_state(facts)
    except Exception as e:
        return {"status": UNKNOWN, "evidence": "coverage state unreadable",
                "gap": f"coverage reader failed: {e}"}
    if not cov.get("available") or cov.get("error"):
        return {"status": UNKNOWN, "evidence": "no parsed coverage to classify",
                "gap": "next-best-test needs real coverage holes to classify"}
    holes = cov.get("holes") or []
    if not holes:
        return {"status": READY,
                "evidence": "no hole to classify (coverage complete)", "gap": ""}
    classified, unclassified, escalate = 0, 0, 0
    try:
        for hole in holes:
            verdict = ca.classify_coverage_hole(facts.root, {"coverage_id": hole.get("name")},
                                                cfg=facts.cfg)
            if verdict.get("recommended_action"):
                classified += 1
            else:
                unclassified += 1
            if verdict.get("requires_human_escalation"):
                escalate += 1
    except Exception as e:
        return {"status": PARTIAL,
                "evidence": f"{len(holes)} hole(s) present",
                "gap": f"hole classifier failed: {e}"}
    evidence = f"{classified}/{len(holes)} hole(s) have a recommended action"
    if escalate:
        evidence += f"; {escalate} need human escalation"
    if unclassified:
        return {"status": PARTIAL, "evidence": evidence,
                "gap": f"{unclassified} hole(s) have no recommended action yet"}
    return {"status": READY, "evidence": evidence, "gap": ""}


def _probe_coverage_closure_loop(facts: _Facts, spec: GoldenFlowRowSpec) -> Dict[str, str]:
    from . import loop_contract as lc
    verdict, evidence, gaps = _stages_verdict(facts, spec)
    loop = None
    if facts.state is None:
        # observe_all() goes through StateStore, which CREATES state.json when
        # none exists. Skipping it here is what keeps this report read-only for
        # a project that has never run -- see the module docstring.
        evidence.append("verification_closure loop NOT_OBSERVABLE")
        gaps.append("no state.json exists yet, so the closure loop has no observable state")
        verdict = combine_readiness([verdict, UNKNOWN])
        return {"status": verdict, "evidence": "; ".join(evidence), "gap": "; ".join(gaps)}
    try:
        observed = lc.observe_all(facts.root, facts.cfg) or {}
        loop = (observed.get("observations") or {}).get(lc.VERIFICATION_CLOSURE_LOOP)
    except Exception as e:
        gaps.append(f"loop observation failed: {e}")
    if not isinstance(loop, dict):
        evidence.append("verification_closure loop NOT_OBSERVABLE")
        gaps.append("the verification closure loop has no observable state yet")
        verdict = combine_readiness([verdict, UNKNOWN])
    else:
        loop_state = loop.get("state") or "NOT_OBSERVABLE"
        evidence.append(f"verification_closure loop state={loop_state}")
        if loop_state == "NOT_OBSERVABLE":
            gaps.append(str(loop.get("reason") or "loop state not observable"))
            verdict = combine_readiness([verdict, UNKNOWN])
    return {"status": verdict, "evidence": "; ".join(evidence), "gap": "; ".join(gaps)}


def _probe_verification_closure_100(facts: _Facts, spec: GoldenFlowRowSpec) -> Dict[str, str]:
    from .dashboard import _coverage_credit, _qualified_conclusion
    verdict, evidence, gaps = _stages_verdict(facts, spec)
    try:
        credit = _coverage_credit(facts.root)
    except Exception as e:
        credit = None
        gaps.append(f"coverage credit unreadable: {e}")
    try:
        conclusion = _qualified_conclusion(facts.root)
    except Exception as e:
        conclusion = None
        gaps.append(f"qualified conclusion unreadable: {e}")
    evidence.append(f"coverage_credit_percent={credit if credit is not None else NONE_CELL}")
    if credit is None:
        gaps.append("COVERAGE_CLOSURE has not recorded a coverage_credit_percent")
        verdict = combine_readiness([verdict, UNKNOWN])
    if conclusion is None:
        evidence.append("qualified_conclusion=NOT_RECORDED")
        gaps.append("no qualified_conclusion has been produced by RE_AUDIT")
        verdict = combine_readiness([verdict, UNKNOWN])
    else:
        qualified = conclusion.get("is_qualified") if isinstance(conclusion, dict) else None
        evidence.append(f"qualified_conclusion.is_qualified={qualified}")
        if qualified is not True:
            gaps.append("the recorded conclusion is not qualified")
            verdict = combine_readiness([verdict, PARTIAL])
    return {"status": verdict, "evidence": "; ".join(evidence), "gap": "; ".join(gaps)}


def _probe_signoff_evidence(facts: _Facts, spec: GoldenFlowRowSpec) -> Dict[str, str]:
    from . import signoff_export as se
    try:
        rec = se.read_signoff_stage_status(facts.root)
    except Exception as e:
        return {"status": UNKNOWN, "evidence": "signoff status unreadable",
                "gap": f"signoff reader failed: {e}"}
    status = (rec or {}).get("stage_status") or se.SIGNOFF_STATUS_NOT_RECORDED
    events = (rec or {}).get("signoff_event_count") or 0
    evidence = (f"SIGNOFF={status}; gate_verified={bool((rec or {}).get('gate_verified'))}; "
                f"{events} SIGNOFF audit event(s)")
    if (rec or {}).get("gate_verified"):
        return {"status": READY, "evidence": evidence, "gap": ""}
    if status == se.SIGNOFF_STATUS_NOT_RECORDED:
        return {"status": UNKNOWN, "evidence": evidence,
                "gap": "SIGNOFF has never recorded a verdict"}
    return {"status": STATUS_TO_READINESS.get(status, UNKNOWN),
            "evidence": evidence,
            "gap": f"SIGNOFF is {status}, not {se.SIGNOFF_VERIFIED_STATUS}"}


def _probe_dashboard(facts: _Facts, spec: GoldenFlowRowSpec) -> Dict[str, str]:
    from . import dashboard as dash
    from . import dashboard_auth
    evidence = []
    gaps = []
    servable = callable(getattr(dash, "serve", None))
    evidence.append("dashboard.serve " + ("available" if servable else "MISSING"))
    if not servable:
        gaps.append("this deployment has no dashboard server")
    try:
        session_path = dashboard_auth.session_file(facts.root)
        has_session = Path(session_path).exists()
    except Exception:
        has_session = False
    evidence.append("auth session token present" if has_session
                    else "auth session token not yet issued")
    return {"status": READY if servable else BLOCKED,
            "evidence": "; ".join(evidence), "gap": "; ".join(gaps)}


def _probe_claude_cli(facts: _Facts, spec: GoldenFlowRowSpec) -> Dict[str, str]:
    from .adapters.cli import ClaudeCLIAdapter
    claude_cfg = (facts.cfg or {}).get("claude") or {}
    adapter = claude_cfg.get("adapter") or "cli"
    configured = claude_cfg.get("command") or "claude"
    resolved = None
    try:
        resolved = ClaudeCLIAdapter._resolve_command(configured)
    except Exception as e:
        return {"status": UNKNOWN, "evidence": f"adapter={adapter}, command={configured}",
                "gap": f"command resolution failed: {e}"}
    found = bool(resolved) and Path(resolved).exists()
    evidence = f"adapter={adapter}; command={configured}; resolved={resolved or NONE_CELL}"
    if found:
        return {"status": READY, "evidence": evidence, "gap": ""}
    return {"status": PARTIAL, "evidence": evidence,
            "gap": f"{configured!r} does not resolve to an executable on this machine"}


def _probe_obsidian_cli(facts: _Facts, spec: GoldenFlowRowSpec) -> Dict[str, str]:
    from . import memory_doctor
    try:
        report = memory_doctor.check_obsidian()
    except Exception as e:
        return {"status": UNKNOWN, "evidence": "obsidian detection unreadable",
                "gap": f"detection failed: {e}"}
    installed = bool(report.get("installed"))
    evidence = (f"status={report.get('status')}; installed={installed}"
                + (f"; version={report.get('version')}" if report.get("version") else ""))
    # Deliberately PARTIAL, never BLOCKED: memory_doctor's own recorded finding
    # is that an absent Obsidian CLI is an expected permanent state and the
    # filesystem adapter is the real write path. Reporting it BLOCKED would
    # make every machine confirmed so far fail a row that is not failing.
    return {"status": READY if installed else PARTIAL, "evidence": evidence,
            "gap": "" if installed else str(report.get("reason") or "")}


def _probe_five_level_memory(facts: _Facts, spec: GoldenFlowRowSpec) -> Dict[str, str]:
    from .dashboard import _read_memory_center_state
    if not (facts.root / ".dv-harness").exists():
        # _read_memory_center_state() calls config.load_config(), which
        # MATERIALIZES a default config.json. An uninitialized project has
        # neither a record store nor a vault, which is exactly the verdict that
        # reader would return -- so report it without provoking the write.
        return {"status": UNKNOWN, "evidence": "no .dv-harness/ tree exists yet",
                "gap": "no memory record has ever been written and no vault exists"}
    try:
        mem = _read_memory_center_state(facts.root)
    except Exception as e:
        return {"status": UNKNOWN, "evidence": "memory center unreadable",
                "gap": f"memory reader failed: {e}"}
    levels = mem.get("levels") or []
    tiers = mem.get("tiers") or []
    if not mem.get("available"):
        return {"status": UNKNOWN,
                "evidence": f"{len(levels)} declared level(s); no store or vault present",
                "gap": "no memory record has ever been written and no vault exists"}

    def _held(tier: Mapping[str, Any]) -> int:
        """Records visible at one tier. `organizational` has no local file
        store by design (memory_router sends it to the shared Knowledge
        Center), so its vault notes are the only local signal -- counting only
        record_files would report a permanently-empty tier that is not empty."""
        return ((tier.get("record_files") or 0) + (tier.get("index_rows") or 0)
                + (tier.get("vault_notes") or 0))

    populated = [t for t in tiers if _held(t) > 0]
    evidence = f"{len(populated)}/{len(levels)} level(s) hold at least one record"
    if not populated:
        return {"status": PARTIAL, "evidence": evidence,
                "gap": "the memory store exists but holds no record at any level"}
    if len(populated) < len(levels):
        empty = [t.get("level") for t in tiers if _held(t) == 0]
        return {"status": PARTIAL, "evidence": evidence,
                "gap": "no record at level(s): " + ", ".join(str(e) for e in empty if e)}
    return {"status": READY, "evidence": evidence, "gap": ""}


#: row_id -> probe. Declared separately from ROWS so a row can never be added
#: without a probe (asserted below) and a probe can never be orphaned.
PROBES: Dict[str, Callable[[_Facts, GoldenFlowRowSpec], Dict[str, str]]] = {
    "spec_in": _probe_spec_in,
    "requirement_extraction": _probe_stage_only,
    "verification_ir": _probe_verification_ir,
    "verification_contract": _probe_stage_only,
    "vplan_traceability": _probe_vplan_traceability,
    "protocol_topology_discovery": _probe_protocol_topology,
    "vip_uvm_generation": _probe_vip_uvm_generation,
    "single_test_proof": _probe_stage_only,
    "lsf_regression": _probe_lsf_regression,
    "failure_triage": _probe_failure_triage,
    "coverage_collection": _probe_coverage_collection,
    "coverage_hole_analysis": _probe_coverage_hole_analysis,
    "next_best_test": _probe_next_best_test,
    "coverage_closure_loop": _probe_coverage_closure_loop,
    "verification_closure_100": _probe_verification_closure_100,
    "signoff_evidence": _probe_signoff_evidence,
    "dashboard": _probe_dashboard,
    "claude_cli_integration": _probe_claude_cli,
    "obsidian_cli_integration": _probe_obsidian_cli,
    "five_level_memory": _probe_five_level_memory,
}


def _assert_every_row_has_a_probe() -> None:
    missing = [r.row_id for r in ROWS if r.row_id not in PROBES]
    orphan = [k for k in PROBES if k not in {r.row_id for r in ROWS}]
    if missing or orphan:
        raise GoldenFlowReadinessError("ROW_PROBE_SET_MISMATCH", {
            "rows_without_probe": missing, "probes_without_row": orphan})


_assert_every_row_has_a_probe()


def assert_fact_sources_resolvable() -> List[str]:
    """Every `fact_source` a row declares still resolves through the import
    system. Returns the resolved names.

    This is the anti-drift check that makes the reuse claim in the module
    docstring checkable rather than asserted: a row saying it reads
    `dashboard._coverage_credit` while that function has been renamed away is a
    row whose evidence provenance is fiction.
    """
    import importlib
    resolved: List[str] = []
    for spec in ROWS:
        for dotted in spec.fact_source:
            # Walk from the longest importable module prefix down the attribute
            # chain, so both `pkg.mod.func` and `pkg.mod.Class.method` resolve.
            parts = dotted.split(".")
            obj = None
            for cut in range(len(parts), 1, -1):
                try:
                    obj = importlib.import_module(".".join(parts[:cut]))
                except Exception:
                    continue
                rest = parts[cut:]
                break
            else:
                raise GoldenFlowReadinessError("FACT_SOURCE_MODULE_UNIMPORTABLE", {
                    "fact_source": dotted, "row": spec.row_id})
            for name in rest:
                if not hasattr(obj, name):
                    raise GoldenFlowReadinessError("FACT_SOURCE_ATTRIBUTE_MISSING", {
                        "fact_source": dotted, "row": spec.row_id, "missing_attribute": name})
                obj = getattr(obj, name)
            resolved.append(dotted)
    return resolved


# ===========================================================================
# The matrix
# ===========================================================================

def derive_golden_flow_readiness(root, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Section 47's matrix for one real project root.

    Read-only and total: every declared row appears in the output, including
    rows whose sources reported absence -- section 47's table is mandatory, and
    "this row is UNKNOWN" and "this row was omitted" must not look alike.
    """
    root = Path(root)
    facts = _gather_facts(root, cfg)
    rows: List[Dict[str, Any]] = []
    for spec in ROWS:
        try:
            probed = PROBES[spec.row_id](facts, spec)
        except Exception as e:  # a probe bug must not delete a mandatory row
            probed = {"status": UNKNOWN, "evidence": NONE_CELL,
                      "gap": f"probe raised {type(e).__name__}: {e}"}
        status = probed.get("status") or UNKNOWN
        if status not in GOLDEN_FLOW_READINESS_CLASSES:
            raise GoldenFlowReadinessError("PROBE_RETURNED_UNKNOWN_READINESS_CLASS", {
                "row": spec.row_id, "status": status,
                "legal_values": list(GOLDEN_FLOW_READINESS_CLASSES)})
        rows.append({
            "row_id": spec.row_id,
            "row": spec.label,
            "status": status,
            "evidence": (probed.get("evidence") or "").strip() or NONE_CELL,
            "gap": (probed.get("gap") or "").strip() or NONE_CELL,
            "next_best_action": NONE_CELL,
            "harness_stages": list(spec.harness_stages),
            "fact_source": list(spec.fact_source),
            "basis": spec.basis,
        })

    # Next-Best-Action only for rows that are not READY: a closed row has no
    # next action, and printing one anyway is how a matrix teaches a reader to
    # ignore the column.
    open_rows = [r["row_id"] for r in rows if r["status"] != READY]
    actions = _next_best_actions(root, open_rows)
    for r in rows:
        if r["row_id"] in actions:
            r["next_best_action"] = actions[r["row_id"]]

    counts = {cls: sum(1 for r in rows if r["status"] == cls)
              for cls in GOLDEN_FLOW_READINESS_CLASSES}
    verdict = combine_readiness([r["status"] for r in rows])
    return {
        "schema_version": SCHEMA_VERSION,
        "root": str(root),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "rows": rows,
        "summary": {
            "rows_total": len(rows),
            **{f"rows_{cls.lower()}": counts[cls] for cls in GOLDEN_FLOW_READINESS_CLASSES},
        },
        "golden_flow_readiness": verdict,
        "readiness_rule": (
            "Section 47: the Golden Flow is READY only when required stages are connected "
            "end-to-end with evidence -- every row READY, with no PARTIAL, BLOCKED or "
            "UNKNOWN row."),
        "authorizes": (
            "nothing. This matrix is an input to a human's signoff decision and to the "
            "section 48 self-check workflow; it approves no promotion and no production "
            "write."),
    }


def _cell(value: Any) -> str:
    """Pipe/newline-safe cell text, the same escaping `system_readiness._cell()`
    applies before its own tables. Done caller-side: a `blocking_reason` read off
    a real state.json can legitimately contain a `|`, and the shared
    `render_markdown_table()` deliberately renders values verbatim."""
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_golden_flow_matrix(matrix: Mapping[str, Any]) -> str:
    """Section 47's table in the document's exact five-column shape.

    The JSON payload keeps every cell's raw text; only this rendered view is
    escaped."""
    from .connectivity import render_markdown_table
    keys = [k for k, _ in GOLDEN_FLOW_MATRIX_COLUMNS]
    rows = [{k: _cell(r.get(k, NONE_CELL)) for k in keys} for r in (matrix.get("rows") or ())]
    return render_markdown_table(
        list(GOLDEN_FLOW_MATRIX_COLUMNS), rows,
        empty_note="(no row was produced -- this is a bug: section 47's twenty rows are "
                   "mandatory even when every one is UNKNOWN)")


def format_golden_flow_readiness_report(matrix: Mapping[str, Any]) -> str:
    """The section 47 report: the verdict, the counts, the table, and the two
    boundaries (what the rule is, what the verdict authorizes)."""
    summary = matrix["summary"]
    out = [
        "# GOLDEN FLOW READINESS MATRIX (section 47)",
        "",
        f"**{matrix['golden_flow_readiness']}** -- {summary['rows_ready']} ready / "
        f"{summary['rows_partial']} partial / {summary['rows_blocked']} blocked / "
        f"{summary['rows_unknown']} unknown, of {summary['rows_total']} rows.",
        "",
        f"Project root: `{matrix['root']}`  (generated {matrix['generated_at']})",
        "",
        render_golden_flow_matrix(matrix),
        "",
        matrix["readiness_rule"],
        "",
        f"This verdict authorizes: {matrix['authorizes']}",
    ]
    blocked = [r for r in matrix.get("rows") or () if r["status"] == BLOCKED]
    if blocked:
        out += ["", "## Blocked rows", ""]
        out += [f"- **{r['row']}** -- {r['gap']}" for r in blocked]
    return "\n".join(out)


# ===========================================================================
# One shared entry point for `dv-harness golden-flow-readiness` and
# `python -m dv_harness.golden_flow_readiness`
# ===========================================================================

def execute(root, *, cfg: Optional[Dict[str, Any]] = None,
            as_json: bool = False) -> Tuple[int, Dict[str, Any], str]:
    """Returns (exit_code, matrix, rendered_text).

    Exit 2 unless the whole matrix is READY. That is NOT an approval signal in
    either direction -- section 47's verdict is an audit input, and a human
    still decides -- but a CI step must not read PARTIAL/BLOCKED/UNKNOWN as a
    clean run. Same convention `dv-harness system-phase1-report` already uses.
    """
    matrix = derive_golden_flow_readiness(root, cfg)
    text = (format_golden_flow_readiness_report(matrix) if not as_json else "")
    return (0 if matrix["golden_flow_readiness"] == READY else 2), matrix, text


def main(argv: Optional[List[str]] = None) -> int:  # pragma: no cover - thin CLI shim
    import argparse
    import json as _json
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.golden_flow_readiness",
        description="Section 47's GOLDEN FLOW READINESS MATRIX, aggregated from this "
                    "project's real per-domain sources. Reads only; runs no stage.")
    ap.add_argument("--project-root", default=".")
    ap.add_argument("--json", action="store_true", dest="as_json")
    args = ap.parse_args(argv)
    code, matrix, text = execute(Path(args.project_root), as_json=args.as_json)
    print(_json.dumps(matrix, ensure_ascii=False, indent=2) if args.as_json else text)
    return code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
