"""End-to-end tests for Section 3 (資源與成本的自主管理), 2026-09-04:

  3a  RTL-diff-driven regression test selection  (dv_harness/change_impact.py
      + the REGRESSION_SELECT engine wiring + the no-shrink enforcement in
      tools/verification_flow/regression_selection_completeness_gate.py)
  3b  seed strategy differentiation              (dv_harness/coverage_analysis.py's
      seed-attempt tracking + differentiated actions, the rewired
      tools/verification_flow/coverage_hole_regeneration_gate.py, and the
      real question-queue escalation the engine performs)
  3c  tiered regression escalation               (dv_harness/regression_tiers.py
      + the per-tier UVM_FATAL threshold in escalation_notify /
      regression_reporter + the `dv-harness regression-tier` CLI)

DELIBERATELY END-TO-END. The audit these close found that the previous
"implementation" of all three was agent self-attestation validated only for
JSON-schema completeness -- code that looked right in isolation and computed
nothing from real data. A unit test that hands `select_regression()` a
hand-built impact dict would have passed just as cheerfully. So every test
below starts from something REAL:

  - a real `git init` repository with real commits, real .sv files and real
    SHAs (never a stubbed `git diff`);
  - a real DuckDB evidence store written through the REAL production write
    path (`regression_reporter._write_reconciliation_evidence_if_configured`)
    from a real `lsf_client.JobState`, for both the rtl_modules join and the
    per-pattern seed counts;
  - a real `.dv-harness/requirements.csv` traceability registry in the exact
    header shape this repo already ships;
  - real gate SUBPROCESSES (`gates.run_gate`), not imported gate functions;
  - a real `QuestionQueueStore` on disk, schema-validated by the queue's own
    validator;
  - the real `DVHarness.run_stage()` path with only the LLM adapter faked.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from dv_harness import change_impact, coverage_analysis, regression_tiers
from dv_harness.escalation_notify import EscalationConfig, EscalationNotifier

ROOT = Path(__file__).resolve().parents[1]

REQUIREMENTS_HEADER = ("REQ_ID,SOURCE,SCOPE,VPLAN_ID,SCENARIO_ID,COMMAND_ID,PATTERN_ID,"
                       "CHECKER_ID,COVERAGE_ID,RESULT,STATUS,EVIDENCE")


# --------------------------------------------------------------------------
# helpers -- real git repo, real registry, real evidence DB
# --------------------------------------------------------------------------

def _git(root, *args, check=True):
    proc = subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True, timeout=60)
    if check and proc.returncode != 0:
        raise AssertionError(f"git {args} failed: {proc.stderr}")
    return proc


def _mk_git_project():
    """A real git repository with a real initial commit."""
    tmp = Path(tempfile.mkdtemp())
    _git(tmp, "init", "-q")
    _git(tmp, "config", "user.email", "test@example.invalid")
    _git(tmp, "config", "user.name", "dv harness test")
    (tmp / "rtl").mkdir(parents=True)
    (tmp / "rtl" / "usb_link_ctrl.sv").write_text("module usb_link_ctrl; endmodule\n", encoding="utf-8")
    (tmp / "rtl" / "usb_phy_if.sv").write_text("module usb_phy_if; endmodule\n", encoding="utf-8")
    (tmp / "docs").mkdir()
    (tmp / "docs" / "notes.md").write_text("notes\n", encoding="utf-8")
    _git(tmp, "add", "-A")
    _git(tmp, "commit", "-q", "-m", "base")
    return tmp


def _write_registry(root, rows, *, commit=False):
    p = Path(root) / ".dv-harness" / "requirements.csv"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(REQUIREMENTS_HEADER + "\n" + "\n".join(rows) + "\n", encoding="utf-8")
    if commit:
        # Committed BEFORE the base SHA is taken, so the registry is not
        # itself part of the diff under test.
        _git(root, "add", "-A")
        _git(root, "commit", "-q", "-m", "traceability registry")


def _run_gate_subprocess(script_name, payload, project_root, flag="--selection"):
    """Runs a REAL gate script as a REAL subprocess with cwd=project_root,
    exactly as dv_harness.gates.run_gate() does."""
    tmp = Path(tempfile.mkdtemp()) / "payload.json"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "verification_flow" / script_name), flag, str(tmp)],
        cwd=str(project_root), capture_output=True, text=True, timeout=60)
    return proc.returncode, json.loads(proc.stdout.strip().splitlines()[-1])


# ==========================================================================
# 3a -- RTL-diff-driven test selection
# ==========================================================================

def test_3a_real_git_diff_drives_a_real_targeted_dependency_selection():
    """The whole 3a chain over REAL data: a real commit touching a real .sv
    file -> real `git diff` -> real requirements.csv traceability -> computed
    TARGETED/DEPENDENCY sets, written to the two real CSVs the
    verification-change-impact skill names."""
    tmp = _mk_git_project()
    try:
        _write_registry(tmp, [
            "REQ-1,spec,usb_link_ctrl,VP-LINK,SC-1,CMD-1,pat_link_up,CHK-1,COV-LINK,PASS,OPEN,ev1",
            "REQ-2,spec,usb_link_ctrl,VP-LINK,SC-2,CMD-2,pat_link_reset,CHK-2,COV-RESET,PASS,OPEN,ev2",
            "REQ-3,spec,usb_phy_if,VP-PHY,SC-3,CMD-3,pat_phy_lock,CHK-3,COV-PHY,PASS,OPEN,ev3",
        ], commit=True)
        base = _git(tmp, "rev-parse", "HEAD").stdout.strip()

        # A REAL change to a REAL RTL file, committed for real.
        (tmp / "rtl" / "usb_link_ctrl.sv").write_text(
            "module usb_link_ctrl;\n  logic extra;\nendmodule\n", encoding="utf-8")
        _git(tmp, "add", "-A")
        _git(tmp, "commit", "-q", "-m", "touch link ctrl")

        cfg = {"regression": {"safety_patterns": ["pat_smoke_boot"],
                              "mandatory_signoff_patterns": ["pat_signoff_full"]}}
        payload = change_impact.compute_and_write(tmp, base_sha=base, cfg=cfg)

        assert payload["diff_status"] == "REAL_DIFF"
        assert payload["changed_files"] == ["rtl/usb_link_ctrl.sv"]

        sel = payload["selection"]
        # TARGETED: both requirements whose SCOPE is the changed module.
        assert sel["targeted_tests"] == ["pat_link_reset", "pat_link_up"]
        # DEPENDENCY: rows sharing a SCOPE/VPLAN grouping with a matched row.
        # pat_phy_lock is a DIFFERENT scope -- it must NOT be pulled in here,
        # which is the whole point of impact-scoped selection.
        assert "pat_phy_lock" not in sel["dependency_tests"]
        # SAFETY/MANDATORY come only from the project's declared sets.
        assert sel["safety_tests"] == ["pat_smoke_boot"]
        assert sel["mandatory_signoff_tests"] == ["pat_signoff_full"]
        assert sel["confidence"] == "HIGH"
        assert sel["expand_to_full_regression"] is False

        # Both real CSV artifacts exist, with the exact pre-existing headers.
        ci = (tmp / ".dv-harness" / "change_impact.csv").read_text(encoding="utf-8").splitlines()
        assert ci[0] == ",".join(change_impact.CHANGE_IMPACT_HEADER)
        assert any("rtl/usb_link_ctrl.sv" in line and "pat_link_up" in line for line in ci[1:])
        rs = (tmp / ".dv-harness" / "regression_selection.csv").read_text(encoding="utf-8").splitlines()
        assert rs[0] == ",".join(change_impact.REGRESSION_SELECTION_HEADER)
        assert any(line.startswith("TARGETED,pat_link_up,") for line in rs[1:])
        assert any(line.startswith("MANDATORY_SIGNOFF,pat_signoff_full,") for line in rs[1:])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_3a_untraceable_high_risk_change_expands_instead_of_narrowing():
    """The skill's own honesty rule as enforced code: a HIGH-risk RTL file
    that traces to NO requirement is an impact gap, and an impact gap must
    EXPAND the selection to the whole known universe, never quietly narrow
    it."""
    tmp = _mk_git_project()
    try:
        _write_registry(tmp, [
            "REQ-1,spec,usb_link_ctrl,VP-LINK,SC-1,CMD-1,pat_link_up,CHK-1,COV-LINK,PASS,OPEN,ev1",
            "REQ-3,spec,usb_phy_if,VP-PHY,SC-3,CMD-3,pat_phy_lock,CHK-3,COV-PHY,PASS,OPEN,ev3",
        ], commit=True)
        base = _git(tmp, "rev-parse", "HEAD").stdout.strip()
        (tmp / "rtl" / "usb_unmapped_dma.sv").write_text("module usb_unmapped_dma; endmodule\n",
                                                          encoding="utf-8")
        _git(tmp, "add", "-A")
        _git(tmp, "commit", "-q", "-m", "new untraced rtl")

        payload = change_impact.compute_and_write(tmp, base_sha=base, cfg={})
        sel = payload["selection"]
        assert payload["unresolved_files"] == ["rtl/usb_unmapped_dma.sv"]
        assert sel["confidence"] == "LOW"
        assert sel["expand_to_full_regression"] is True
        # Both known patterns pulled in, despite neither being "targeted".
        assert sorted(sel["dependency_tests"]) == ["pat_link_up", "pat_phy_lock"]
        assert sorted(sel["expansion_added"]) == ["pat_link_up", "pat_phy_lock"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_3a_doc_only_change_does_not_expand():
    """The counterpart honesty check: a documentation-only commit is a real
    HIGH-confidence "no design impact", not an impact gap. Without this, the
    expansion rule above would make every commit a full regression and the
    whole mechanism would be worthless."""
    tmp = _mk_git_project()
    try:
        _write_registry(tmp, [
            "REQ-1,spec,usb_link_ctrl,VP-LINK,SC-1,CMD-1,pat_link_up,CHK-1,COV-LINK,PASS,OPEN,ev1",
        ], commit=True)
        base = _git(tmp, "rev-parse", "HEAD").stdout.strip()
        (tmp / "docs" / "notes.md").write_text("notes v2\n", encoding="utf-8")
        _git(tmp, "add", "-A")
        _git(tmp, "commit", "-q", "-m", "docs")

        payload = change_impact.compute_and_write(tmp, base_sha=base, cfg={})
        assert payload["selection"]["expand_to_full_regression"] is False
        assert payload["selection"]["confidence"] == "HIGH"
        assert payload["unresolved_files"] == []
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_3a_rtl_module_join_uses_real_verible_parse_rows():
    """The DESIGN-IMPACT hop specifically: a changed file whose PATH STEM
    matches nothing in the registry still resolves, because the real
    `rtl_modules` rows (written by the real insert_rtl_parse()) say which
    MODULE that file declares, and the registry's SCOPE names the module."""
    pytest.importorskip("duckdb")
    from dv_harness.evidence_db import EvidenceStore, default_db_path

    tmp = _mk_git_project()
    try:
        # Registry keyed on the MODULE name, which differs from the filename.
        _write_registry(tmp, [
            "REQ-9,spec,link_training_fsm,VP-LT,SC-9,CMD-9,pat_link_training,CHK-9,COV-LT,PASS,OPEN,ev9",
        ])
        with EvidenceStore(default_db_path(tmp)) as store:
            store.insert_rtl_parse({
                "file_path": "/home/dv/proj/rtl/u_ctrl_top.sv",
                "source_sha256": "abc123", "verible_version": "v0.0-test",
                "modules": [{"name": "link_training_fsm", "ports": [], "signals": [],
                             "parameters": []}],
            })

        base = _git(tmp, "rev-parse", "HEAD").stdout.strip()
        (tmp / "rtl" / "u_ctrl_top.sv").write_text("module link_training_fsm; endmodule\n",
                                                    encoding="utf-8")
        _git(tmp, "add", "-A")
        _git(tmp, "commit", "-q", "-m", "add ctrl top")

        payload = change_impact.compute_and_write(tmp, base_sha=base, cfg={})
        assert payload["rtl_parse_available"] is True
        assert payload["selection"]["targeted_tests"] == ["pat_link_training"]
        assert payload["selection"]["expand_to_full_regression"] is False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_3a_harness_metadata_changes_are_not_design_impact():
    """Found by the first end-to-end run of the test above: a commit that
    only touches the harness's OWN bookkeeping under `.dv-harness/` was being
    scored MEDIUM-risk-and-untraceable, which forced `expand_to_full_regression`
    -- i.e. every registry/state edit would have cost a full regression."""
    assert change_impact.classify_risk(".dv-harness/requirements.csv") == change_impact.RISK_LOW
    assert change_impact.classify_risk(".claude/skills/CORE/x/SKILL.md") == change_impact.RISK_LOW
    assert change_impact.classify_risk("docs/notes.md") == change_impact.RISK_LOW
    # ...while real design and testbench source keep their real risk levels.
    assert change_impact.classify_risk("rtl/usb_link_ctrl.sv") == change_impact.RISK_HIGH
    assert change_impact.classify_risk("tb/usb_env/usb_seq.sv") == change_impact.RISK_MEDIUM
    assert change_impact.classify_risk("tb/patterns/usb_link/command.txt") == change_impact.RISK_MEDIUM
    # An unrecognised file type never talks its way down to LOW.
    assert change_impact.classify_risk("scripts/build.tcl") == change_impact.RISK_MEDIUM


def test_3a_gate_rejects_a_selection_that_drops_a_computed_test():
    """The enforcement half, through a REAL gate subprocess: the agent may
    add, never drop. Before this, the gate could not tell the difference --
    it only counted non-empty categories."""
    tmp = _mk_git_project()
    try:
        _write_registry(tmp, [
            "REQ-1,spec,usb_link_ctrl,VP-LINK,SC-1,CMD-1,pat_link_up,CHK-1,COV-LINK,PASS,OPEN,ev1",
            "REQ-2,spec,usb_link_ctrl,VP-LINK,SC-2,CMD-2,pat_link_reset,CHK-2,COV-RESET,PASS,OPEN,ev2",
        ], commit=True)
        base = _git(tmp, "rev-parse", "HEAD").stdout.strip()
        (tmp / "rtl" / "usb_link_ctrl.sv").write_text("module usb_link_ctrl;\n logic x;\nendmodule\n",
                                                       encoding="utf-8")
        _git(tmp, "add", "-A")
        _git(tmp, "commit", "-q", "-m", "change")
        cfg = {"regression": {"safety_patterns": ["pat_smoke"],
                              "mandatory_signoff_patterns": ["pat_signoff"]}}
        payload = change_impact.compute_and_write(tmp, base_sha=base, cfg=cfg)
        eid = payload["change_impact_evidence_id"]

        # (1) Dropping a computed targeted test FAILS.
        rc, out = _run_gate_subprocess(
            "regression_selection_completeness_gate.py",
            {"targeted_tests": ["pat_link_up"],  # pat_link_reset dropped
             "dependency_tests": ["pat_link_reset_dep_placeholder"],
             "safety_tests": ["pat_smoke"], "mandatory_signoff_tests": ["pat_signoff"],
             "selection_source": {"change_impact_evidence_id": eid}},
            tmp)
        assert rc == 6, out
        assert out["reason"] == "COMPUTED_SELECTION_TESTS_DROPPED"
        assert out["dropped"] == ["pat_link_reset"]

        # (2) Keeping all computed tests AND adding one of the agent's own PASSes.
        rc, out = _run_gate_subprocess(
            "regression_selection_completeness_gate.py",
            {"targeted_tests": ["pat_link_up", "pat_link_reset", "pat_agent_extra"],
             "dependency_tests": ["pat_dep"],
             "safety_tests": ["pat_smoke"], "mandatory_signoff_tests": ["pat_signoff"],
             "selection_source": {"change_impact_evidence_id": eid}},
            tmp)
        assert rc == 0, out
        assert out["status"] == "PASS"
        assert out["computed_selection_checked"] is True

        # (3) A fabricated evidence id FAILS -- the link is now checkable.
        rc, out = _run_gate_subprocess(
            "regression_selection_completeness_gate.py",
            {"targeted_tests": ["pat_link_up", "pat_link_reset"], "dependency_tests": ["pat_dep"],
             "safety_tests": ["pat_smoke"], "mandatory_signoff_tests": ["pat_signoff"],
             "selection_source": {"change_impact_evidence_id": "CI-totally-made-up"}},
            tmp)
        assert rc == 5, out
        assert out["reason"] == "CHANGE_IMPACT_EVIDENCE_ID_MISMATCH"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_3a_gate_is_unchanged_when_no_computed_selection_exists():
    """Backward compatibility, proven rather than asserted: with no computed
    artifact on disk the gate behaves exactly as it did before this change."""
    tmp = Path(tempfile.mkdtemp())
    try:
        rc, out = _run_gate_subprocess(
            "regression_selection_completeness_gate.py",
            {"targeted_tests": ["t1"], "dependency_tests": ["d1"],
             "safety_tests": ["s1"], "mandatory_signoff_tests": ["m1"],
             "selection_source": {"change_impact_evidence_id": "anything-goes-here"}},
            tmp)
        assert rc == 0, out
        assert out["computed_selection_checked"] is False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_3a_run_stage_computes_the_selection_and_shows_it_to_the_agent():
    """The INVOCATION half: REGRESSION_SELECT must actually trigger the
    computation. This drives the real DVHarness.run_stage() with only the
    LLM adapter faked, and asserts (a) the computed artifact really landed on
    disk and (b) the real prompt the agent received carried the computed
    sets."""
    from dv_harness.engine import DVHarness
    from dv_harness.adapters.base import AgentResult

    tmp = _mk_git_project()
    try:
        (tmp / ".dv-harness" / "graph").mkdir(parents=True, exist_ok=True)
        (tmp / ".dv-harness" / "graph" / "main_graph.json").write_text(
            (ROOT / ".dv-harness" / "graph" / "main_graph.json").read_text(encoding="utf-8"),
            encoding="utf-8")
        _write_registry(tmp, [
            "REQ-1,spec,usb_link_ctrl,VP-LINK,SC-1,CMD-1,pat_link_up,CHK-1,COV-LINK,PASS,OPEN,ev1",
        ])
        (tmp / "rtl" / "usb_link_ctrl.sv").write_text("module usb_link_ctrl;\n logic y;\nendmodule\n",
                                                       encoding="utf-8")
        _git(tmp, "add", "-A")
        _git(tmp, "commit", "-q", "-m", "engine-wiring change")
        # Copied AFTER the commit on purpose: `git add -A` over the whole
        # tools/ + .claude/agents/ trees takes minutes on Windows, and these
        # files are stage-execution inputs, not part of the diff under test.
        shutil.copytree(ROOT / ".claude" / "agents", tmp / ".claude" / "agents")
        shutil.copytree(ROOT / "tools", tmp / "tools")

        prompts = []

        class _Adapter:
            def run(self, prompt, cwd, resume_session=None, agent_profile=None):
                prompts.append(prompt)
                return AgentResult(ok=True, text="selected.", raw={}, session_id=None)

        h = DVHarness(tmp)
        h.adapter = _Adapter()
        h.cfg["policy"]["require_stage_gate_evidence"] = False
        h.cfg["regression"] = {"safety_patterns": ["pat_smoke"],
                               "mandatory_signoff_patterns": ["pat_signoff"]}
        h.set_stage("REGRESSION_SELECT")
        h.run_stage("select the regression subset")

        computed = change_impact.read_computed_selection(tmp)
        assert computed is not None, "REGRESSION_SELECT did not compute a selection"
        assert computed["diff_status"] == "REAL_DIFF"
        assert computed["selection"]["targeted_tests"] == ["pat_link_up"]

        assert prompts, "adapter was never called"
        assert "change_impact_evidence_id" in prompts[0]
        assert "pat_link_up" in prompts[0]
        assert computed["change_impact_evidence_id"] in prompts[0]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ==========================================================================
# 3b -- seed strategy differentiation
# ==========================================================================

def _record_job(root, pattern, seed, job_id):
    """Drives the REAL production evidence write path for one job."""
    from dv_harness import lsf_client
    from dv_harness import regression_reporter as rr
    state = lsf_client.JobState(job_id=job_id, pattern=pattern, seed=str(seed),
                                 lsf_status="DONE", sim_status="PASS")
    rr._write_reconciliation_evidence_if_configured(root, {job_id: (state, [])})


def _enable_evidence_db(root):
    from dv_harness import config as _config
    cfg = _config.load_config(root)
    cfg.setdefault("evidence_db", {})["enabled"] = True
    (Path(root) / ".dv-harness" / "config.json").write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def test_3b_seed_attempts_come_from_real_job_rows():
    pytest.importorskip("duckdb")
    tmp = Path(tempfile.mkdtemp())
    try:
        _enable_evidence_db(tmp)
        for i, seed in enumerate([11, 22, 33, 33]):  # 33 repeated -> 3 DISTINCT
            _record_job(tmp, "pat_link_up", seed, 1000 + i)
        counts = coverage_analysis.count_seed_attempts(tmp, ["pat_link_up", "pat_never_run"])
        assert counts["pat_link_up"] == 3
        assert counts["pat_never_run"] == 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_3b_under_sampled_bin_routes_to_add_seeds_not_a_new_testcase():
    """The 'not run enough yet -> add seeds' branch that did not exist at all
    before. Note the agent CLAIMED UNREACHABLE_STIMULUS -- with only 3 real
    seeds recorded, that claim is not supportable and is downgraded."""
    pytest.importorskip("duckdb")
    tmp = Path(tempfile.mkdtemp())
    try:
        _enable_evidence_db(tmp)
        _write_registry(tmp, [
            "REQ-1,spec,usb_link_ctrl,VP-LINK,SC-1,CMD-1,pat_link_up,CHK-1,COV-LINK,PASS,OPEN,ev1",
        ])
        for i, seed in enumerate([1, 2, 3]):
            _record_job(tmp, "pat_link_up", seed, 2000 + i)

        v = coverage_analysis.classify_coverage_hole(
            tmp, {"coverage_id": "COV-LINK", "root_cause_classification": "UNREACHABLE_STIMULUS"})
        assert v["linked_patterns"] == ["pat_link_up"]
        assert v["distinct_seed_attempts"] == 3
        assert v["classification"] == coverage_analysis.ROOT_CAUSE_INSUFFICIENT_SEED_ATTEMPTS
        assert v["recommended_action"] == coverage_analysis.ACTION_ADD_SEEDS
        assert v["requires_human_escalation"] is False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_3b_adequately_sampled_unreachable_bin_escalates_to_the_real_question_queue():
    """The differentiated action the old gate structurally forbade: once the
    bin HAS been sampled enough, UNREACHABLE_STIMULUS goes to a real,
    schema-validated Tier-3 question owned by the designer -- not to 'write
    another testcase'."""
    pytest.importorskip("duckdb")
    from dv_harness.question_queue import QuestionQueueStore, TIER3_CANNOT_ASSUME

    tmp = Path(tempfile.mkdtemp())
    try:
        _enable_evidence_db(tmp)
        _write_registry(tmp, [
            "REQ-1,spec,usb_link_ctrl,VP-LINK,SC-1,CMD-1,pat_link_up,CHK-1,COV-LINK,PASS,OPEN,ev1",
        ])
        for i in range(25):  # >= DEFAULT_MIN_SEED_ATTEMPTS
            _record_job(tmp, "pat_link_up", 100 + i, 3000 + i)

        v = coverage_analysis.classify_coverage_hole(
            tmp, {"coverage_id": "COV-LINK", "root_cause_classification": "UNREACHABLE_STIMULUS"})
        assert v["distinct_seed_attempts"] == 25
        assert v["classification"] == coverage_analysis.ROOT_CAUSE_UNREACHABLE_STIMULUS
        assert v["recommended_action"] == coverage_analysis.ACTION_ESCALATE_TO_HUMAN
        assert v["requires_human_escalation"] is True

        results = coverage_analysis.escalate_unreachable_holes(
            tmp, [{"coverage_id": "COV-LINK", "root_cause_classification": "UNREACHABLE_STIMULUS"}])
        qid = results[0]["question_id"]
        assert qid

        store = QuestionQueueStore(tmp)
        q = store.get_question(qid)
        assert q["tier"] == TIER3_CANNOT_ASSUME
        assert q["blocking"] is True
        assert q["owner"] == "designer"
        assert q["status"] == "OPEN"
        assert q["context_path"] == "coverage/COV-LINK"

        # Idempotent: the same bin escalated again does not mint a second
        # question_key (the queue's own "asked once" guarantee, inherited).
        again = coverage_analysis.escalate_unreachable_holes(
            tmp, [{"coverage_id": "COV-LINK", "root_cause_classification": "UNREACHABLE_STIMULUS"}])
        assert store.get_question(again[0]["question_id"])["question_key"] == q["question_key"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_3b_no_seed_history_does_not_fabricate_an_under_sampled_verdict():
    """Also found by the first end-to-end run: with NO evidence DB at all,
    every pattern reports 0 seed attempts -- and treating that as a real
    measurement made the seed rule fire for every hole, permanently
    suppressing the escalation path. Reporting 0 from a store that was never
    written is not a measurement, so the seed gate is skipped and the agent's
    classification stands, with the reason recorded."""
    tmp = Path(tempfile.mkdtemp())
    try:
        _write_registry(tmp, [
            "REQ-1,spec,usb_link_ctrl,VP-LINK,SC-1,CMD-1,pat_link_up,CHK-1,COV-LINK,PASS,OPEN,ev1",
        ])
        assert coverage_analysis.seed_history_available(tmp) is False
        v = coverage_analysis.classify_coverage_hole(
            tmp, {"coverage_id": "COV-LINK", "root_cause_classification": "UNREACHABLE_STIMULUS"})
        assert v["seed_history_available"] is False
        assert v["classification"] == coverage_analysis.ROOT_CAUSE_UNREACHABLE_STIMULUS
        assert v["requires_human_escalation"] is True
        assert "NO_SEED_RUN_HISTORY_AVAILABLE" in v["basis"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_3b_bin_with_no_traced_pattern_is_a_computed_missing_test():
    tmp = Path(tempfile.mkdtemp())
    try:
        _write_registry(tmp, [
            "REQ-1,spec,usb_link_ctrl,VP-LINK,SC-1,CMD-1,pat_link_up,CHK-1,COV-LINK,PASS,OPEN,ev1",
        ])
        v = coverage_analysis.classify_coverage_hole(tmp, {"coverage_id": "COV-ORPHAN"})
        assert v["classification"] == coverage_analysis.ROOT_CAUSE_MISSING_TEST
        assert v["recommended_action"] == coverage_analysis.ACTION_GENERATE_TESTCASE
        assert v["basis"] == "NO_PATTERN_TRACED_TO_COVERAGE_ID_IN_REQUIREMENTS_REGISTRY"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_3b_gate_no_longer_demands_a_testcase_for_an_unreachable_bin():
    """The miswiring itself, fixed and proven through a REAL gate subprocess:
    UNREACHABLE_STIMULUS with a real escalation and NO regenerated testcase
    now PASSES (it used to FAIL with COVERAGE_HOLE_WITHOUT_TEST_REGENERATION),
    and the same hole with no escalation at all FAILS."""
    from dv_harness.question_queue import QuestionQueueStore

    tmp = Path(tempfile.mkdtemp())
    try:
        store = QuestionQueueStore(tmp)
        q = store.add_question(
            domain="dut", question="is COV-LINK structurally unreachable?",
            context_path="coverage/COV-LINK",
            options=[{"label": "STRUCTURALLY_UNREACHABLE"}, {"label": "REACHABLE_STIMULUS_GAP"}],
            recommendation="STRUCTURALLY_UNREACHABLE",
            assumption_if_unanswered="none",
            context={"affects_pass_fail_verdict": True})

        rc, out = _run_gate_subprocess(
            "coverage_hole_regeneration_gate.py",
            {"coverage_holes": [{"coverage_id": "COV-LINK", "waived": False,
                                  "root_cause_classification": "UNREACHABLE_STIMULUS",
                                  "escalation_question_id": q["id"]}]},
            tmp, flag="--holes")
        assert rc == 0, out
        assert out["question_queue_checked"] is True

        rc, out = _run_gate_subprocess(
            "coverage_hole_regeneration_gate.py",
            {"coverage_holes": [{"coverage_id": "COV-LINK", "waived": False,
                                  "root_cause_classification": "UNREACHABLE_STIMULUS"}]},
            tmp, flag="--holes")
        assert rc == 7, out
        assert out["reason"] == "UNREACHABLE_STIMULUS_WITHOUT_HUMAN_ESCALATION"

        # A fabricated question id is caught against the real queue.
        rc, out = _run_gate_subprocess(
            "coverage_hole_regeneration_gate.py",
            {"coverage_holes": [{"coverage_id": "COV-LINK", "waived": False,
                                  "root_cause_classification": "UNREACHABLE_STIMULUS",
                                  "escalation_question_id": "Q-DOES-NOT-EXIST"}]},
            tmp, flag="--holes")
        assert rc == 8, out
        assert out["reason"] == "ESCALATION_QUESTION_ID_NOT_IN_QUEUE"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_3b_gate_keeps_the_regeneration_requirement_for_the_two_classes_that_need_it():
    tmp = Path(tempfile.mkdtemp())
    try:
        for cls in ("MISSING_TEST", "INSUFFICIENT_CONSTRAINT"):
            rc, out = _run_gate_subprocess(
                "coverage_hole_regeneration_gate.py",
                {"coverage_holes": [{"coverage_id": "c1", "waived": False,
                                      "root_cause_classification": cls}]},
                tmp, flag="--holes")
            assert rc == 4, out
            assert out["reason"] == "COVERAGE_HOLE_WITHOUT_TEST_REGENERATION"

            rc, out = _run_gate_subprocess(
                "coverage_hole_regeneration_gate.py",
                {"coverage_holes": [{"coverage_id": "c1", "waived": False,
                                      "root_cause_classification": cls,
                                      "regenerated_testcase_ids": ["t1"],
                                      "rerun_evidence": "ev"}]},
                tmp, flag="--holes")
            assert rc == 0, out

        # And the new seed class needs added-seed evidence, not a testcase.
        rc, out = _run_gate_subprocess(
            "coverage_hole_regeneration_gate.py",
            {"coverage_holes": [{"coverage_id": "c1", "waived": False,
                                  "root_cause_classification": "INSUFFICIENT_SEED_ATTEMPTS"}]},
            tmp, flag="--holes")
        assert rc == 6, out
        assert out["reason"] == "INSUFFICIENT_SEEDS_WITHOUT_ADDED_SEED_EVIDENCE"

        rc, out = _run_gate_subprocess(
            "coverage_hole_regeneration_gate.py",
            {"coverage_holes": [{"coverage_id": "c1", "waived": False,
                                  "root_cause_classification": "INSUFFICIENT_SEED_ATTEMPTS",
                                  "added_seed_evidence": "seeds 100..149 rerun, job 4711"}]},
            tmp, flag="--holes")
        assert rc == 0, out

        # An unrecognised class no longer slips through unremediated.
        rc, out = _run_gate_subprocess(
            "coverage_hole_regeneration_gate.py",
            {"coverage_holes": [{"coverage_id": "c1", "waived": False,
                                  "root_cause_classification": "SOMETHING_ELSE"}]},
            tmp, flag="--holes")
        assert rc == 9, out
        assert out["reason"] == "UNKNOWN_COVERAGE_HOLE_CLASSIFICATION"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_3b_run_stage_performs_the_escalation_for_the_agent():
    """The engine wiring: an agent response classifying a hole
    UNREACHABLE_STIMULUS causes a REAL question-queue entry to be created by
    the harness, before the gate that checks for it runs."""
    from dv_harness.engine import DVHarness
    from dv_harness.adapters.base import AgentResult
    from dv_harness.question_queue import QuestionQueueStore

    tmp = Path(tempfile.mkdtemp())
    try:
        (tmp / ".dv-harness" / "graph").mkdir(parents=True)
        (tmp / ".dv-harness" / "graph" / "main_graph.json").write_text(
            (ROOT / ".dv-harness" / "graph" / "main_graph.json").read_text(encoding="utf-8"),
            encoding="utf-8")
        shutil.copytree(ROOT / ".claude" / "agents", tmp / ".claude" / "agents")
        shutil.copytree(ROOT / "tools", tmp / "tools")
        # A real traceability row, so the bin genuinely has a pattern traced
        # to it -- without one the computed verdict is (correctly)
        # MISSING_TEST, not an unreachability claim worth a designer's time.
        _write_registry(tmp, [
            "REQ-7,spec,usb_link_ctrl,VP-LINK,SC-7,CMD-7,pat_link_up,CHK-7,COV-UNREACH,PASS,OPEN,ev7",
        ])

        holes = {"coverage_holes": [{"coverage_id": "COV-UNREACH", "waived": False,
                                      "root_cause_classification": "UNREACHABLE_STIMULUS"}]}
        text = ("done.\n```dv-harness-evidence:coverage_hole_regeneration_gate\n"
                + json.dumps(holes) + "\n```\n")

        class _Adapter:
            def run(self, prompt, cwd, resume_session=None, agent_profile=None):
                return AgentResult(ok=True, text=text, raw={}, session_id=None)

        h = DVHarness(tmp)
        h.adapter = _Adapter()
        h.cfg["policy"]["require_stage_gate_evidence"] = False
        h.set_stage("COVERAGE_CLOSURE")
        h.run_stage("close coverage")

        qs = QuestionQueueStore(tmp).list_questions()
        assert len(qs) == 1, qs
        assert qs[0]["context_path"] == "coverage/COV-UNREACH"
        assert qs[0]["owner"] == "designer"
        assert qs[0]["blocking"] is True
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ==========================================================================
# 3c -- tiered regression escalation
# ==========================================================================

def test_3c_each_tier_admits_a_different_test_set():
    selection = {
        "targeted_tests": ["pat_t1"], "dependency_tests": ["pat_d1"],
        "safety_tests": ["pat_smoke"], "mandatory_signoff_tests": ["pat_signoff"],
    }
    universe = ["pat_t1", "pat_d1", "pat_smoke", "pat_signoff", "pat_rare_corner"]

    smoke = regression_tiers.tests_for_tier("SMOKE", selection, full_pattern_universe=universe)
    assert smoke["tests"] == ["pat_smoke", "pat_signoff"]
    assert smoke["policy"]["time_budget_minutes"] == 10

    nightly = regression_tiers.tests_for_tier("NIGHTLY", selection, full_pattern_universe=universe)
    assert sorted(nightly["tests"]) == ["pat_d1", "pat_signoff", "pat_smoke", "pat_t1"]
    assert "pat_rare_corner" not in nightly["tests"]

    weekly = regression_tiers.tests_for_tier("WEEKLY", selection, full_pattern_universe=universe)
    assert "pat_rare_corner" in weekly["tests"]
    assert weekly["full_regression"] is True
    assert weekly["full_universe_available"] is True


def test_3c_unknown_tier_is_a_hard_error_never_a_silent_default():
    with pytest.raises(ValueError):
        regression_tiers.policy_for("NIGHLTY")  # typo


def test_3c_per_tier_uvm_fatal_threshold_actually_changes_whether_escalation_fires():
    class _Fake:
        def __init__(self):
            self.sent = []

        def send(self, title, body, tags=None):
            self.sent.append((title, body, tags))
            return True

    # Two fatals: below the flat/NIGHTLY threshold of 3, at/above SMOKE's 1.
    t = _Fake()
    n = EscalationNotifier(EscalationConfig(enabled=True), transport=t)
    flat = n.uvm_fatal_burst(2)
    assert flat.fired is False and t.sent == []

    smoke_threshold = regression_tiers.policy_for("SMOKE").uvm_fatal_burst_threshold
    ev = n.uvm_fatal_burst(2, tier="SMOKE", threshold=smoke_threshold)
    assert ev.fired is True
    assert "tier=SMOKE" in ev.reason
    assert len(t.sent) == 1

    weekly_threshold = regression_tiers.policy_for("WEEKLY").uvm_fatal_burst_threshold
    ev = n.uvm_fatal_burst(4, tier="WEEKLY", threshold=weekly_threshold)
    assert ev.fired is False, "4 fatals across a full weekly universe is not the burst signal"


def test_3c_reconciliation_cycle_applies_the_active_tier_threshold():
    """The real production escalation path, end to end: the SAME two-fatal
    batch escalates or does not escalate purely because of which tier was
    declared active -- proving the tier record is genuinely consulted by
    regression_reporter, not just readable in isolation."""
    from dv_harness import regression_reporter as rr

    tmp = Path(tempfile.mkdtemp())
    try:
        rows = [{"job_id": 1, "uvm_fatal_count": 1}, {"job_id": 2, "uvm_fatal_count": 1}]

        sent = []

        class _Fake:
            def send(self, title, body, tags=None):
                sent.append(body)
                return True

        import dv_harness.escalation_notify as en
        real_from_config = en.notifier_from_config
        en.notifier_from_config = lambda cfg, transport=None: EscalationNotifier(
            en.config_from_dict(cfg or {"enabled": True}), transport=_Fake())
        try:
            # No tier declared -> flat threshold 3 -> two fatals do NOT escalate.
            rr._escalate_uvm_fatal_burst_if_needed(tmp, rows)
            assert sent == []

            # SMOKE declared -> threshold 1 -> the same two fatals DO escalate.
            regression_tiers.record_active_tier(tmp, "SMOKE", tests=["pat_smoke"])
            rr._escalate_uvm_fatal_burst_if_needed(tmp, rows)
            assert len(sent) == 1
            assert "tier=SMOKE" in sent[0]

            # Cleared -> back to flat behavior.
            regression_tiers.clear_active_tier(tmp)
            rr._escalate_uvm_fatal_burst_if_needed(tmp, rows)
            assert len(sent) == 1
        finally:
            en.notifier_from_config = real_from_config
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_3c_config_json_overrides_a_tier_policy():
    cfg = {"regression_tiers": {"SMOKE": {"time_budget_minutes": 5,
                                           "uvm_fatal_burst_threshold": 2}}}
    p = regression_tiers.policy_for("SMOKE", cfg)
    assert p.time_budget_minutes == 5
    assert p.uvm_fatal_burst_threshold == 2
    # Untouched tiers keep their defaults.
    assert regression_tiers.policy_for("NIGHTLY", cfg).uvm_fatal_burst_threshold == 3


def test_3c_cli_start_records_a_real_active_tier_from_a_real_diff():
    """The full 3a+3c join through the REAL CLI as a REAL subprocess: a real
    commit -> computed selection -> tier-resolved test list -> an active-tier
    record on disk that the escalation path will read."""
    tmp = _mk_git_project()
    try:
        _write_registry(tmp, [
            "REQ-1,spec,usb_link_ctrl,VP-LINK,SC-1,CMD-1,pat_link_up,CHK-1,COV-LINK,PASS,OPEN,ev1",
            "REQ-3,spec,usb_phy_if,VP-PHY,SC-3,CMD-3,pat_phy_lock,CHK-3,COV-PHY,PASS,OPEN,ev3",
        ], commit=True)
        base = _git(tmp, "rev-parse", "HEAD").stdout.strip()
        (tmp / "rtl" / "usb_link_ctrl.sv").write_text("module usb_link_ctrl;\n logic z;\nendmodule\n",
                                                       encoding="utf-8")
        _git(tmp, "add", "-A")
        _git(tmp, "commit", "-q", "-m", "cli change")

        cfg_path = tmp / ".dv-harness" / "config.json"
        from dv_harness import config as _config
        cfg = _config.load_config(tmp)
        cfg["regression"] = {"safety_patterns": ["pat_smoke"],
                             "mandatory_signoff_patterns": ["pat_signoff"]}
        cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

        proc = subprocess.run(
            [sys.executable, "-m", "dv_harness.cli", "--project-root", str(tmp),
             "regression-tier", "start", "NIGHTLY", "--base-sha", base],
            capture_output=True, text=True, timeout=120, cwd=str(ROOT))
        assert proc.returncode == 0, proc.stderr
        out = json.loads(proc.stdout)
        assert out["tier"] == "NIGHTLY"
        assert "pat_link_up" in out["tests"]
        assert "pat_smoke" in out["tests"] and "pat_signoff" in out["tests"]
        assert out["change_impact_evidence_id"].startswith("CI-")

        record = regression_tiers.read_active_tier(tmp)
        assert record["tier"] == "NIGHTLY"
        assert record["policy"]["uvm_fatal_burst_threshold"] == 3
        assert regression_tiers.active_uvm_fatal_burst_threshold(tmp) == 3

        proc = subprocess.run(
            [sys.executable, "-m", "dv_harness.cli", "--project-root", str(tmp),
             "regression-tier", "status"],
            capture_output=True, text=True, timeout=120, cwd=str(ROOT))
        assert proc.returncode == 0, proc.stderr
        assert json.loads(proc.stdout)["tier"] == "NIGHTLY"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
