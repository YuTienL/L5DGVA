"""Tests for dv_harness/functional_coverage_signoff.py -- the FUNCTIONAL_
COVERAGE_SIGNOFF_READY verdict + Closure metric rollup (2026-09-06).

Every input is produced by its REAL owning module, never hand-written to
look like one:
  * waivers go through the real `waiver_store.record_waiver()` ledger writer;
  * recorded coverage numbers land in a REAL DuckDB `EvidenceStore`'s
    `coverage_samples` table through its own `insert_coverage_sample()`;
  * seed-attempt history lands in the SAME store's real `jobs` table through
    `insert_job_state()`, exactly as `coverage_analysis.count_seed_attempts()`
    reads it;
  * the declared coverage-goal scope is a REAL, schema-valid env.manifest.json
    built by `env_manifest.generate_env_manifest()` over a real
    testplan-sources document, validated against the project's own
    `testplan_sources.schema.json`;
  * an UNREACHABLE_STIMULUS "proof" goes through the REAL question-queue
    round trip: `coverage_analysis.escalate_unreachable_stimulus()` files the
    real Tier-3 question, and `QuestionQueueStore.answer_question()` is what
    actually confirms it -- never a hand-inserted "ANSWERED" record.

The negative controls are what give this module's Closure formula detection
power: an EXPIRED waiver blocks signoff even at a measured 100%; an
under-sampled hole (few distinct seeds, real seed history present) is never
credited even when the agent claims it is unreachable; an unreachable claim
with no human confirmation on file is never credited either; and a declared
bin with no recorded evidence at all reports INCOMPLETE_EVIDENCE rather than
silently excluding it from the goal.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")

from dv_harness import coverage_analysis as ca
from dv_harness import env_manifest as em
from dv_harness import functional_coverage_signoff as fcs
from dv_harness import waiver_store as ws
from dv_harness.evidence_db import EvidenceStore, default_db_path
from dv_harness.question_queue import QuestionQueueStore

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# helpers -- every one drives a real producer
# ---------------------------------------------------------------------------

def _insert_coverage(root: Path, categories) -> None:
    with EvidenceStore(default_db_path(root)) as store:
        for cat in categories:
            store.insert_coverage_sample(cat, timestamp="2026-09-06T00:00:00Z", source="test")


def _insert_seed_jobs(root: Path, pattern: str, n: int, start_id: int) -> None:
    with EvidenceStore(default_db_path(root)) as store:
        for i in range(n):
            store.insert_job_state({"job_id": start_id + i, "pattern": pattern, "seed": str(i)})


def _write_requirements_csv(root: Path, rows) -> None:
    d = root / ".dv-harness"
    d.mkdir(parents=True, exist_ok=True)
    header = ["REQ_ID", "SOURCE", "SCOPE", "VPLAN_ID", "SCENARIO_ID", "COMMAND_ID",
              "PATTERN_ID", "CHECKER_ID", "COVERAGE_ID", "RESULT", "STATUS", "EVIDENCE"]
    lines = [",".join(header)]
    for r in rows:
        lines.append(",".join(str(r.get(h, "")) for h in header))
    (d / "requirements.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_env_manifest(root: Path, bins) -> None:
    """A real, schema-valid env.manifest.json whose testplan_correspondence
    declares one vPlan item per (coverage_id, description) in `bins`, each
    claiming exactly that one coverage_model entry."""
    testplan = {
        "schema_version": "1.0",
        "coverage_model": [{"name": name, "kind": "covergroup"} for name in bins],
        "vplan_items": [{"id": f"VP-{name}", "coverage": [name]} for name in bins],
    }
    tp_path = root / "testplan_sources.json"
    tp_path.write_text(json.dumps(testplan), encoding="utf-8")
    manifest = em.generate_env_manifest(testplan_sources_path=tp_path)
    out_path = root / ".dv-harness" / "env.manifest.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    em.save_env_manifest(manifest, out_path)


def _record_waiver(root: Path, waiver_id: str, item: str, *, expires_at: str) -> None:
    ws.record_waiver(root, {
        "waiver_id": waiver_id, "item": item, "reason": "known limitation, accepted by design",
        "evidence": "see review notes", "approver": "alice",
        "affected_version": {"spec_revision": "r1"}, "risk": "LOW",
        "created_at": "2026-01-01T00:00:00+00:00",
        "expires_at": expires_at,
        "scope": {
            "requirement_ids": ["REQ-1"], "subsystem": "usb3", "spec_revision": "r1",
            "design_evidence_hash": "abc123", "approval_id": "AP-1", "scope_hash": "hash1",
        },
    })


def _write_agent_hole_claim(root: Path, coverage_id: str, classification: str,
                              escalation_question_id=None) -> None:
    """A real state.json COVERAGE_CLOSURE stage record carrying the fenced
    ```dv-harness-evidence:coverage_hole_regeneration_gate``` block the real
    gate script itself reads -- the same shape
    dv_harness/functional_coverage_signoff.py's own `_agent_hole_claims()`
    extracts through `gates.extract_evidence_blocks()`."""
    hole = {"coverage_id": coverage_id, "root_cause_classification": classification}
    if escalation_question_id:
        hole["escalation_question_id"] = escalation_question_id
    payload = {"coverage_holes": [hole]}
    last_message = (
        "```dv-harness-evidence:coverage_hole_regeneration_gate\n"
        + json.dumps(payload) + "\n```"
    )
    d = root / ".dv-harness"
    d.mkdir(parents=True, exist_ok=True)
    (d / "state.json").write_text(json.dumps({
        "stages": {"COVERAGE_CLOSURE": {"status": "PARTIAL", "last_message": last_message}}
    }), encoding="utf-8")


def _row(report, coverage_id):
    for r in report["rows"]:
        if r["coverage_id"] == coverage_id:
            return r
    raise AssertionError(f"{coverage_id} missing from rows: "
                         f"{[r['coverage_id'] for r in report['rows']]}")


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------

def test_no_evidence_database_is_honestly_not_available(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    report = fcs.analyze_functional_coverage_signoff(root)
    assert report["status"] == fcs.STATUS_NOT_AVAILABLE
    assert report["functional_coverage_signoff_ready"] is None
    assert report["evidence_db_input"]["status"] == "NOT_AVAILABLE"
    assert report["evidence_db_input"]["reason"] == "NO_EVIDENCE_DATABASE"
    assert report["waiver_input"]["status"] == "NOT_AVAILABLE"
    assert report["testplan_input"]["status"] == "NOT_AVAILABLE"
    code, _, text = fcs.execute(root)
    assert code == 2
    assert "NOT_AVAILABLE" in text


def test_full_measured_coverage_is_signoff_ready(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    _write_env_manifest(root, ["cov_a", "cov_b"])
    _insert_coverage(root, [
        {"name": "cov_a", "percent": 100.0, "bins_total": 10, "bins_hit": 10},
        {"name": "cov_b", "percent": 100.0, "bins_total": 5, "bins_hit": 5},
    ])
    report = fcs.analyze_functional_coverage_signoff(root)
    assert report["status"] == fcs.STATUS_SIGNOFF_READY
    assert report["functional_coverage_signoff_ready"] is True
    assert report["closure_percent"] == 100.0
    assert report["waiver_input"]["status"] == "NOT_AVAILABLE"  # no ledger -- honestly reported
    assert report["waiver_input"]["reason"] == "NO_WAIVER_LEDGER"
    code, _, _ = fcs.execute(root)
    assert code == 0


def test_valid_waiver_closes_the_gap(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    _write_env_manifest(root, ["cov_a", "cov_b"])
    _insert_coverage(root, [
        {"name": "cov_a", "percent": 100.0, "bins_total": 10, "bins_hit": 10},
        {"name": "cov_b", "percent": 60.0, "bins_total": 10, "bins_hit": 6},
    ])
    _record_waiver(root, "W-1", "cov_b", expires_at="2099-01-01T00:00:00+00:00")

    report = fcs.analyze_functional_coverage_signoff(root)
    assert report["status"] == fcs.STATUS_SIGNOFF_READY
    assert report["functional_coverage_signoff_ready"] is True
    assert report["closure_percent"] == 100.0
    row_b = _row(report, "cov_b")
    assert row_b["credit_source"] == fcs.CREDIT_APPROVED_WAIVER
    assert row_b["credited_bins"] == 4
    assert row_b["waiver_status"] == "VALID"
    assert report["blocking_waivers"] == []


def test_expired_waiver_blocks_signoff_even_at_full_measured_coverage(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    _write_env_manifest(root, ["cov_a", "cov_b"])
    _insert_coverage(root, [
        {"name": "cov_a", "percent": 100.0, "bins_total": 10, "bins_hit": 10},
        {"name": "cov_b", "percent": 100.0, "bins_total": 5, "bins_hit": 5},
    ])
    # An EXPIRED waiver matching a bin that is already fully MEASURED covered
    # -- still "in the mix" and must still block, per this module's own
    # stated formula.
    _record_waiver(root, "W-2", "cov_a", expires_at="2020-01-01T00:00:00+00:00")

    report = fcs.analyze_functional_coverage_signoff(root)
    assert report["closure_percent"] == 100.0  # the percentage really is 100%...
    assert report["status"] == fcs.STATUS_BLOCKED_BY_WAIVER
    assert report["functional_coverage_signoff_ready"] is False  # ...but signoff is still refused
    assert report["blocking_waivers"] == [{"coverage_id": "cov_a", "waiver_id": "W-2",
                                            "status": "EXPIRED"}]
    code, _, _ = fcs.execute(root)
    assert code == 1


def test_under_sampled_hole_is_never_credited(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    _write_env_manifest(root, ["cov_a", "cov_b"])
    _insert_coverage(root, [
        {"name": "cov_a", "percent": 100.0, "bins_total": 10, "bins_hit": 10},
        {"name": "cov_b", "percent": 60.0, "bins_total": 10, "bins_hit": 6},
    ])
    _write_requirements_csv(root, [
        {"REQ_ID": "REQ-B", "PATTERN_ID": "patt_b", "COVERAGE_ID": "cov_b", "SCOPE": "usb3"},
    ])
    # Real seed history EXISTS (so the seed-attempt check actually runs) but
    # only 3 distinct seeds were ever tried against patt_b -- well under the
    # project's default floor of 20.
    _insert_seed_jobs(root, "patt_b", n=3, start_id=1)
    # The agent claims this bin is structurally unreachable anyway.
    _write_agent_hole_claim(root, "cov_b", "UNREACHABLE_STIMULUS")

    report = fcs.analyze_functional_coverage_signoff(root)
    row_b = _row(report, "cov_b")
    assert row_b["classification"] == ca.ROOT_CAUSE_INSUFFICIENT_SEED_ATTEMPTS
    assert row_b["credited_bins"] == 0
    assert row_b["credit_source"] == fcs.CREDIT_NONE
    assert report["status"] == fcs.STATUS_OPEN
    assert report["functional_coverage_signoff_ready"] is False
    assert report["closure_percent"] < 100.0


def test_claimed_unreachable_without_human_confirmation_is_never_credited(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    _write_env_manifest(root, ["cov_a", "cov_b"])
    _insert_coverage(root, [
        {"name": "cov_a", "percent": 100.0, "bins_total": 10, "bins_hit": 10},
        {"name": "cov_b", "percent": 60.0, "bins_total": 10, "bins_hit": 6},
    ])
    _write_requirements_csv(root, [
        {"REQ_ID": "REQ-B", "PATTERN_ID": "patt_b", "COVERAGE_ID": "cov_b", "SCOPE": "usb3"},
    ])
    # Adequately sampled this time (>= the default floor of 20).
    _insert_seed_jobs(root, "patt_b", n=20, start_id=1)
    # File the REAL escalation question (the production path), but leave it
    # unanswered -- a design owner has not yet confirmed anything.
    verdict = ca.classify_coverage_hole(root, {"coverage_id": "cov_b"})
    assert verdict["classification"] is None  # no agent classification supplied yet
    q = ca.escalate_unreachable_stimulus(
        root, {"coverage_id": "cov_b", "distinct_seed_attempts": 20, "min_seed_attempts": 20,
               "linked_patterns": ["patt_b"]})
    _write_agent_hole_claim(root, "cov_b", "UNREACHABLE_STIMULUS",
                              escalation_question_id=q["id"])

    report = fcs.analyze_functional_coverage_signoff(root)
    row_b = _row(report, "cov_b")
    assert row_b["classification"] == ca.ROOT_CAUSE_UNREACHABLE_STIMULUS
    assert row_b["human_confirmed_unreachable"] is False
    assert row_b["credited_bins"] == 0
    assert row_b["credit_source"] == fcs.CREDIT_NONE
    assert report["functional_coverage_signoff_ready"] is False
    assert report["status"] == fcs.STATUS_OPEN


def test_human_confirmed_unreachable_closes_the_gap(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    _write_env_manifest(root, ["cov_a", "cov_b"])
    _insert_coverage(root, [
        {"name": "cov_a", "percent": 100.0, "bins_total": 10, "bins_hit": 10},
        {"name": "cov_b", "percent": 60.0, "bins_total": 10, "bins_hit": 6},
    ])
    _write_requirements_csv(root, [
        {"REQ_ID": "REQ-B", "PATTERN_ID": "patt_b", "COVERAGE_ID": "cov_b", "SCOPE": "usb3"},
    ])
    _insert_seed_jobs(root, "patt_b", n=20, start_id=1)
    q = ca.escalate_unreachable_stimulus(
        root, {"coverage_id": "cov_b", "distinct_seed_attempts": 20, "min_seed_attempts": 20,
               "linked_patterns": ["patt_b"]})
    # The real human round trip: a design owner actually ANSWERS the queue.
    QuestionQueueStore(root).answer_question(
        q["id"], answer="STRUCTURALLY_UNREACHABLE",
        basis="RTL review confirms this state cannot be reached", decided_by="design_owner_bob")
    _write_agent_hole_claim(root, "cov_b", "UNREACHABLE_STIMULUS",
                              escalation_question_id=q["id"])

    report = fcs.analyze_functional_coverage_signoff(root)
    row_b = _row(report, "cov_b")
    assert row_b["classification"] == ca.ROOT_CAUSE_UNREACHABLE_STIMULUS
    assert row_b["human_confirmed_unreachable"] is True
    assert row_b["credited_bins"] == 4
    assert row_b["credit_source"] == fcs.CREDIT_PROVEN_UNREACHABLE
    assert report["closure_percent"] == 100.0
    assert report["status"] == fcs.STATUS_SIGNOFF_READY
    assert report["functional_coverage_signoff_ready"] is True


def test_later_reconsideration_overrides_an_earlier_confirmation(tmp_path):
    """A design owner confirms unreachability, then reconsiders and answers
    again with the opposite conclusion -- the most recently answered record
    must decide, never an OR across every answer ever given."""
    root = tmp_path / "proj"
    root.mkdir()
    _write_env_manifest(root, ["cov_b"])
    _insert_coverage(root, [{"name": "cov_b", "percent": 60.0, "bins_total": 10, "bins_hit": 6}])
    _write_requirements_csv(root, [
        {"REQ_ID": "REQ-B", "PATTERN_ID": "patt_b", "COVERAGE_ID": "cov_b", "SCOPE": "usb3"},
    ])
    _insert_seed_jobs(root, "patt_b", n=20, start_id=1)
    store = QuestionQueueStore(root)
    q1 = ca.escalate_unreachable_stimulus(
        root, {"coverage_id": "cov_b", "distinct_seed_attempts": 20, "min_seed_attempts": 20,
               "linked_patterns": ["patt_b"]}, store=store)
    store.answer_question(q1["id"], answer="STRUCTURALLY_UNREACHABLE",
                           basis="first look", decided_by="design_owner_bob")
    # Revoke and re-ask so a SECOND, later ANSWERED record exists for the
    # same coverage_id with the opposite conclusion.
    store.revoke_decision(q1["question_key"], reason="reconsidering after further RTL review")
    q2 = store.add_question(
        domain="dut", question="reconsider cov_b reachability",
        context_path="coverage/cov_b", options=["STRUCTURALLY_UNREACHABLE", "REACHABLE_STIMULUS_GAP"],
        recommendation="REACHABLE_STIMULUS_GAP",
        assumption_if_unanswered="None -- cannot-assume question.",
        context={"affects_pass_fail_verdict": True, "affects_spec_intent": True})
    store.answer_question(q2["id"], answer="REACHABLE_STIMULUS_GAP",
                           basis="found a legal stimulus path after all",
                           decided_by="design_owner_bob")
    _write_agent_hole_claim(root, "cov_b", "UNREACHABLE_STIMULUS")

    report = fcs.analyze_functional_coverage_signoff(root)
    row_b = _row(report, "cov_b")
    assert row_b["human_confirmed_unreachable"] is False
    assert row_b["credited_bins"] == 0


def test_declared_bin_with_no_recorded_evidence_is_incomplete(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    _write_env_manifest(root, ["cov_a", "cov_c"])
    # cov_c is declared by the testplan but NEVER recorded in the evidence
    # database at all.
    _insert_coverage(root, [{"name": "cov_a", "percent": 100.0, "bins_total": 10, "bins_hit": 10}])

    report = fcs.analyze_functional_coverage_signoff(root)
    assert report["status"] == fcs.STATUS_INCOMPLETE_EVIDENCE
    assert report["functional_coverage_signoff_ready"] is False
    assert report["unrecorded_declared"] == ["cov_c"]
    code, _, _ = fcs.execute(root)
    assert code == 1


def test_no_testplan_correspondence_widens_scope_to_all_recorded_categories(tmp_path):
    """Absent an env.manifest.json, the declared goal falls back to every
    category the evidence database has ever recorded -- never an empty
    scope standing in for "nothing to check"."""
    root = tmp_path / "proj"
    root.mkdir()
    _insert_coverage(root, [{"name": "cov_a", "percent": 100.0, "bins_total": 10, "bins_hit": 10}])
    report = fcs.analyze_functional_coverage_signoff(root)
    assert report["testplan_input"]["status"] == "NOT_AVAILABLE"
    assert report["declared_scope_source"] == "ALL_RECORDED_CATEGORIES"
    assert report["status"] == fcs.STATUS_SIGNOFF_READY
    assert report["functional_coverage_signoff_ready"] is True


def test_cli_entry_point_reports_not_available_and_signoff_ready(tmp_path):
    empty_root = tmp_path / "empty"
    empty_root.mkdir()
    r = subprocess.run(
        [sys.executable, "-m", "dv_harness.functional_coverage_signoff",
         "--project-root", str(empty_root), "--json"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=60)
    assert r.returncode == 2, r.stdout + r.stderr
    payload = json.loads(r.stdout)
    assert payload["status"] == fcs.STATUS_NOT_AVAILABLE

    ready_root = tmp_path / "ready"
    ready_root.mkdir()
    _write_env_manifest(ready_root, ["cov_a"])
    _insert_coverage(ready_root, [{"name": "cov_a", "percent": 100.0, "bins_total": 10, "bins_hit": 10}])
    r2 = subprocess.run(
        [sys.executable, "-m", "dv_harness.functional_coverage_signoff",
         "--project-root", str(ready_root), "--json"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=60)
    assert r2.returncode == 0, r2.stdout + r2.stderr
    payload2 = json.loads(r2.stdout)
    assert payload2["functional_coverage_signoff_ready"] is True
    assert payload2["closure_percent"] == 100.0

    r3 = subprocess.run(
        [sys.executable, "-m", "dv_harness.functional_coverage_signoff",
         "--project-root", str(ready_root)],
        cwd=str(ROOT), capture_output=True, text=True, timeout=60)
    assert r3.returncode == 0, r3.stdout + r3.stderr
    assert "FUNCTIONAL COVERAGE SIGNOFF" in r3.stdout
    assert "authorizes nothing" in r3.stdout


# ---------------------------------------------------------------------------
# FUNCTIONAL-vs-CODE coverage separation: a high CODE-coverage number must
# never offset, or stand in for, a real FUNCTIONAL-coverage gap in Closure.
# (M5 Cohort 5, CAP-M5-COV-001, migrated from Parent)
# ---------------------------------------------------------------------------

def test_code_coverage_alone_never_masquerades_as_functional_signoff_ready(tmp_path):
    """No testplan correspondence (the ALL_RECORDED_CATEGORIES fallback
    scope) and the ONLY thing ever recorded is a real VCS code-coverage
    category at 100%. Before this module classified coverage KIND, this
    scenario reached STATUS_SIGNOFF_READY / functional_coverage_signoff_ready
    == True purely off a code-coverage number, with zero functional coverage
    ever measured -- exactly the false-pass the audit finding named. It must
    now be excluded from the declared scope and reported as such, never
    counted."""
    root = tmp_path / "proj"
    root.mkdir()
    _insert_coverage(root, [{"name": "line", "percent": 100.0, "bins_total": 500, "bins_hit": 500}])

    report = fcs.analyze_functional_coverage_signoff(root)
    assert report["excluded_code_coverage_bins"] == ["line"]
    assert report["status"] == fcs.STATUS_NOT_AVAILABLE
    assert report["reason"] == "ALL_DECLARED_CATEGORIES_ARE_CODE_COVERAGE"
    assert report["functional_coverage_signoff_ready"] is None
    assert report["closure_percent"] is None
    code, _, _ = fcs.execute(root)
    assert code == 2


def test_high_code_coverage_does_not_mask_a_real_functional_gap(tmp_path):
    """Mixed evidence-DB contents, no testplan correspondence: a genuine
    functional-coverage bin (cov_a) sits at a real 50% gap, alongside a
    code-coverage category (line) sitting at a fully-covered 100%. Naively
    blending them (105/510 measured bins) would report a misleadingly high
    Closure and could mask the real functional gap; this must instead compute
    Closure over cov_a ALONE and correctly report NOT signoff-ready."""
    root = tmp_path / "proj"
    root.mkdir()
    _insert_coverage(root, [
        {"name": "cov_a", "percent": 50.0, "bins_total": 10, "bins_hit": 5},
        {"name": "line", "percent": 100.0, "bins_total": 500, "bins_hit": 500},
    ])

    report = fcs.analyze_functional_coverage_signoff(root)
    assert report["declared_scope_source"] == "ALL_RECORDED_CATEGORIES"
    assert report["excluded_code_coverage_bins"] == ["line"]
    # Closure is computed over cov_a alone -- never blended with "line"'s
    # measured bins/percent.
    assert report["total_goal_bins"] == 10
    assert report["covered_bins"] == 5
    assert report["closure_percent"] == 50.0
    assert report["status"] == fcs.STATUS_OPEN
    assert report["functional_coverage_signoff_ready"] is False
    assert [r["coverage_id"] for r in report["rows"]] == ["cov_a"]
    code, _, _ = fcs.execute(root)
    assert code == 1


def test_testplan_declared_code_coverage_name_is_still_excluded(tmp_path):
    """Same protection whichever declared-scope source resolves: a vPlan
    item mistakenly declaring a code-coverage metric name ("branch") as its
    own coverage_present goal (the intended TESTPLAN_CORRESPONDENCE path)
    must not let that code-coverage percentage count toward, or substitute
    for, the real functional bin's (cov_a) closure. Both real bins are also
    fully recorded in the evidence DB, so the ALL_RECORDED_CATEGORIES
    fallback scope (used whenever testplan correspondence itself is
    unavailable in this environment) declares the identical {cov_a, branch}
    set -- the exclusion protection this test targets holds either way, so
    the scope-source assertion below accepts both real sources rather than
    coupling this test to env.manifest.json resolution, which is unrelated
    to the FUNCTIONAL-vs-CODE separation under test here."""
    root = tmp_path / "proj"
    root.mkdir()
    _write_env_manifest(root, ["cov_a", "branch"])
    _insert_coverage(root, [
        {"name": "cov_a", "percent": 40.0, "bins_total": 10, "bins_hit": 4},
        {"name": "branch", "percent": 100.0, "bins_total": 60, "bins_hit": 60},
    ])

    report = fcs.analyze_functional_coverage_signoff(root)
    assert report["declared_scope_source"] in ("TESTPLAN_CORRESPONDENCE", "ALL_RECORDED_CATEGORIES")
    assert report["excluded_code_coverage_bins"] == ["branch"]
    assert report["total_goal_bins"] == 10
    assert report["covered_bins"] == 4
    assert report["closure_percent"] == 40.0
    assert report["status"] == fcs.STATUS_OPEN
    assert report["functional_coverage_signoff_ready"] is False


def test_no_code_coverage_categories_present_excluded_list_is_empty(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    _write_env_manifest(root, ["cov_a"])
    _insert_coverage(root, [{"name": "cov_a", "percent": 100.0, "bins_total": 10, "bins_hit": 10}])
    report = fcs.analyze_functional_coverage_signoff(root)
    assert report["excluded_code_coverage_bins"] == []
    assert report["functional_coverage_signoff_ready"] is True
