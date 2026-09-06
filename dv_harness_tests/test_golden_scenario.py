"""Tests for dv_harness/golden_scenario.py -- spec section 225's golden
scenario / reference capsule store (2026-09-06).

Everything here runs against REAL machinery, not stand-ins:
  * a REAL throwaway git repository with real commits, so freshness is
    derived from a real `git diff` between two real SHAs;
  * a REAL DuckDB `EvidenceStore` with this project's real schema;
  * a REAL `vip_distill.distill_sim_log()` envelope produced from a synthetic
    sim.log written in this project's own documented FINAL CHECK epilogue
    format -- the capsule is recorded against evidence the real distiller
    produced, never a hand-written dict shaped to look like one;
  * a REAL `lsf_client.JobState` row, so `verified_sha` is picked up from the
    real `jobs.git_sha` column rather than supplied by the test.

The central proof (`test_rtl_change_makes_capsule_stale`) records a capsule
against a real PASS, asserts FRESH, then makes a REAL RTL commit and asserts
the SAME capsule is STALE naming that file -- the full record-then-detect
round trip section 225 asks for.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys

import pytest

duckdb = pytest.importorskip("duckdb")

from dv_harness import golden_scenario as gs
from dv_harness.evidence_db import EvidenceStore
from dv_harness.lsf_client import JobState
from dv_harness.vip_distill import distill_sim_log

GIT = shutil.which("git")
requires_git = pytest.mark.skipif(GIT is None, reason="git is not on PATH")

PASSING_SIM_LOG = """\
UVM_INFO @ 0 ns: reporter [RNTST] Running test usb3_lfps_basic...
UVM_INFO @ 1200 ns: uvm_test_top.env.usb3_agent [LFPS] link training complete
FINAL CHECK @ 25000 ns
UVM_FATAL = 0, UVM_ERROR = 0, UVM_WARNING = 0
VERDICT: PASSED
"""

FAILING_SIM_LOG = """\
UVM_ERROR @ 900 ns: uvm_test_top.env.usb3_agent [LFPS] handshake timeout
FINAL CHECK @ 25000 ns
UVM_FATAL = 0, UVM_ERROR = 1, UVM_WARNING = 0
VERDICT: FAILED
"""

TEST_NAME = "usb3_lfps_basic"
JOB_ID = 987654


def _git(root, *args, check=True):
    r = subprocess.run([GIT, *args], cwd=str(root), capture_output=True, text=True,
                       timeout=120, encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        raise AssertionError(f"git {args} failed ({r.returncode}):\n{r.stdout}\n{r.stderr}")
    return r


def _commit(root, message):
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", message)
    return _git(root, "rev-parse", "HEAD").stdout.strip()


@pytest.fixture()
def project(tmp_path):
    """A throwaway project: a real git repo holding a DUT RTL tree, a VIP
    config, a command.txt pattern and a doc, with one initial commit."""
    root = tmp_path / "proj"
    (root / "rtl" / "usb3_link").mkdir(parents=True)
    (root / "vip" / "usb3").mkdir(parents=True)
    (root / "patterns").mkdir(parents=True)
    (root / "doc").mkdir(parents=True)
    (root / "rtl" / "usb3_link" / "usb3_link_ctrl.v").write_text(
        "module usb3_link_ctrl(input clk, input rst_n, output reg lfps_done);\n"
        "always @(posedge clk) lfps_done <= rst_n;\nendmodule\n", encoding="utf-8")
    (root / "vip" / "usb3" / "usb3_vip_cfg.sv").write_text(
        "// svt_usb_configuration knobs for the usb3 agent\n", encoding="utf-8")
    (root / "patterns" / "command.txt").write_text("LFPS_INIT\nLINK_TRAIN\n", encoding="utf-8")
    (root / "doc" / "notes.md").write_text("# notes\n", encoding="utf-8")
    # The evidence DuckDB and the simulation run directory are harness/run
    # artifacts, not project sources -- and an open DuckDB file cannot be
    # indexed by git on Windows at all.
    (root / ".gitignore").write_text(".dv-harness/\nrun/\n", encoding="utf-8")
    subprocess.run([GIT, "init", "-q", "-b", "master", str(root)], check=True, timeout=60)
    _git(root, "config", "user.email", "golden-scenario@example.invalid")
    _git(root, "config", "user.name", "golden-scenario-test")
    sha = _commit(root, "initial DUT + VIP config + pattern")
    return root, sha


@pytest.fixture()
def store(project):
    root, _ = project
    s = EvidenceStore(root / ".dv-harness" / "evidence" / "evidence.duckdb")
    yield s
    s.close()


def _ingest_passing_evidence(store, root, sha, *, log_text=PASSING_SIM_LOG,
                              pattern=TEST_NAME, job_id=JOB_ID):
    """Real distiller output for a real sim.log, ingested through the real
    store, with the real JobState row carrying the git SHA it ran against."""
    log_path = root / "run" / str(job_id) / "sim.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(log_text, encoding="utf-8")
    envelope = distill_sim_log(log_path=log_path, job_id=job_id, pattern=pattern,
                               protocol="USB3", run_dir=str(log_path.parent))
    store.insert_normalized_evidence(envelope)
    store.insert_job_state(JobState(
        job_id=job_id, regression_id="REG-GS-1", pattern=pattern,
        run_dir=str(log_path.parent), sim_log=str(log_path), seed="42",
        lsf_status="DONE", sim_status="PASS", uvm_error_count=0, uvm_fatal_count=0,
        git_sha=sha,
    ))
    return envelope


def _capsule(evidence_id, **overrides):
    base = dict(
        capsule_id=gs.default_capsule_id("usb3_soc", "usb3_link", TEST_NAME, "42"),
        project="usb3_soc", subsystem="usb3_link", test_name=TEST_NAME,
        evidence_id=evidence_id, protocol="USB3",
        sequence_name="usb3_lfps_basic_vseq", seed="42",
        requirements=["REQ-USB3-LFPS-001"],
        vip_versions={"svt_usb": "2024.09", "vcs": "2023.12-SP2"},
        configuration={"speed": "SS", "ports": 1},
        command_txt_inputs=["patterns/command.txt"],
        known_limitations=["single port only; no U1/U2 low-power entry exercised"],
        watched_paths=["rtl/usb3_link", "vip/usb3", "patterns"],
    )
    base.update(overrides)
    return gs.GoldenScenario(**base)


# --- the real evidence guard ----------------------------------------------


@requires_git
def test_record_requires_real_evidence_row(project, store):
    root, sha = project
    _ingest_passing_evidence(store, root, sha)
    with pytest.raises(gs.EvidenceNotFoundError):
        gs.record_golden_scenario(store, _capsule("EVID-does-not-exist"))
    assert store.list_golden_scenarios() == []


@requires_git
def test_record_refuses_a_failing_run(project, store):
    """A capsule is a proven-good claim, so real FAILED evidence must not be
    recordable as golden -- checked against the real distiller's own verdict
    for a real failing sim.log, not a hand-set field."""
    root, sha = project
    envelope = _ingest_passing_evidence(store, root, sha, log_text=FAILING_SIM_LOG,
                                        job_id=JOB_ID + 1)
    assert envelope["verdict"] == "FAILED"
    with pytest.raises(gs.EvidenceNotPassingError):
        gs.record_golden_scenario(store, _capsule(envelope["evidence_id"]))
    assert store.list_golden_scenarios() == []


@requires_git
def test_record_refuses_evidence_for_a_different_test(project, store):
    root, sha = project
    envelope = _ingest_passing_evidence(store, root, sha, pattern="usb3_u1_entry",
                                        job_id=JOB_ID + 2)
    with pytest.raises(gs.EvidenceMismatchError):
        gs.record_golden_scenario(store, _capsule(envelope["evidence_id"]))


def test_validate_capsule_rejects_a_non_pass_expected_result():
    with pytest.raises(gs.CapsuleValidationError):
        gs.validate_capsule(_capsule("EVID-x", expected_result="FAILED"))
    with pytest.raises(gs.CapsuleValidationError):
        gs.validate_capsule(_capsule("EVID-x", test_name=""))


def test_capsule_from_json_rejects_an_unknown_field():
    with pytest.raises(gs.CapsuleValidationError):
        gs.capsule_from_json({"project": "p", "subsystem": "s", "test_name": "t",
                              "evidence_id": "e", "watched_path": ["rtl"]})


# --- recording + round trip ------------------------------------------------


@requires_git
def test_record_fills_identity_from_the_real_evidence_and_job_rows(project, store):
    root, sha = project
    envelope = _ingest_passing_evidence(store, root, sha)
    stored = gs.record_golden_scenario(store, _capsule(
        envelope["evidence_id"], protocol=None, job_id=None, verified_sha=None))
    # job_id and protocol came off the real normalized_evidence row; the SHA
    # came off the real jobs row that evidence belongs to.
    assert stored.job_id == JOB_ID
    assert stored.protocol == "USB3"
    assert stored.verified_sha == sha
    assert stored.verified_at

    round_tripped = gs.load_golden_scenario(store, stored.capsule_id)
    assert round_tripped.verified_sha == sha
    assert round_tripped.requirements == ["REQ-USB3-LFPS-001"]
    assert round_tripped.vip_versions == {"svt_usb": "2024.09", "vcs": "2023.12-SP2"}
    assert round_tripped.configuration == {"speed": "SS", "ports": 1}
    assert round_tripped.watched_paths == ["rtl/usb3_link", "vip/usb3", "patterns"]
    assert round_tripped.known_limitations and "single port" in round_tripped.known_limitations[0]

    row = store.get_golden_scenario(stored.capsule_id)
    assert row["evidence_verdict"] == "PASSED"


@requires_git
def test_re_recording_the_same_capsule_updates_one_row(project, store):
    """A capsule re-verified against a newer commit updates its own row --
    it must not accumulate a second capsule for the same test."""
    root, sha = project
    envelope = _ingest_passing_evidence(store, root, sha)
    first = gs.record_golden_scenario(store, _capsule(envelope["evidence_id"]))

    (root / "doc" / "notes.md").write_text("# notes\nsecond\n", encoding="utf-8")
    sha2 = _commit(root, "docs only")
    envelope2 = _ingest_passing_evidence(store, root, sha2, job_id=JOB_ID + 5)
    second = gs.record_golden_scenario(store, _capsule(envelope2["evidence_id"]))

    assert first.capsule_id == second.capsule_id
    assert len(store.list_golden_scenarios()) == 1
    assert gs.load_golden_scenario(store, first.capsule_id).verified_sha == sha2


# --- freshness derived from REAL git history -------------------------------


@requires_git
def test_fresh_when_nothing_changed(project, store):
    root, sha = project
    envelope = _ingest_passing_evidence(store, root, sha)
    capsule = gs.record_golden_scenario(store, _capsule(envelope["evidence_id"]))
    result = gs.evaluate_freshness(root, capsule)
    assert result["freshness"] == gs.FRESH
    assert result["diff_status"] == "REAL_DIFF"
    assert result["changed_files_in_scope"] == []


@requires_git
def test_documentation_change_does_not_stale_a_capsule(project, store):
    root, sha = project
    envelope = _ingest_passing_evidence(store, root, sha)
    capsule = gs.record_golden_scenario(store, _capsule(envelope["evidence_id"]))
    (root / "doc" / "notes.md").write_text("# notes\nmore prose\n", encoding="utf-8")
    _commit(root, "doc only")
    result = gs.evaluate_freshness(root, capsule)
    assert result["freshness"] == gs.FRESH, result["reasons"]


@requires_git
def test_rtl_change_makes_capsule_stale(project, store):
    """The section 225 round trip: record a proven-good capsule against real
    PASS evidence, confirm FRESH, then make a REAL RTL commit and confirm the
    SAME capsule goes STALE naming that file at HIGH risk."""
    root, sha = project
    envelope = _ingest_passing_evidence(store, root, sha)
    capsule = gs.record_golden_scenario(store, _capsule(envelope["evidence_id"]))
    assert gs.evaluate_freshness(root, capsule)["freshness"] == gs.FRESH

    rtl = root / "rtl" / "usb3_link" / "usb3_link_ctrl.v"
    rtl.write_text(rtl.read_text(encoding="utf-8").replace(
        "lfps_done <= rst_n;", "lfps_done <= rst_n & 1'b1;"), encoding="utf-8")
    head = _commit(root, "usb3_link_ctrl: gate lfps_done")

    result = gs.evaluate_freshness(root, capsule)
    assert result["freshness"] == gs.STALE
    assert result["head_sha"] == head
    triggering = {t["path"]: t["risk"] for t in result["triggering_changes"]}
    assert triggering == {"rtl/usb3_link/usb3_link_ctrl.v": "HIGH"}
    assert any("DESIGN_OR_CONFIG_CHANGED_SINCE_VERIFIED_SHA" in r for r in result["reasons"])
    # The capsule row itself is untouched -- freshness is derived, never stored.
    assert gs.load_golden_scenario(store, capsule.capsule_id).verified_sha == sha


@requires_git
def test_vip_config_change_makes_capsule_stale(project, store):
    root, sha = project
    envelope = _ingest_passing_evidence(store, root, sha)
    capsule = gs.record_golden_scenario(store, _capsule(envelope["evidence_id"]))
    cfg = root / "vip" / "usb3" / "usb3_vip_cfg.sv"
    cfg.write_text(cfg.read_text(encoding="utf-8") + "// enable scrambling\n", encoding="utf-8")
    _commit(root, "usb3 vip config change")
    result = gs.evaluate_freshness(root, capsule)
    assert result["freshness"] == gs.STALE
    assert [t["path"] for t in result["triggering_changes"]] == ["vip/usb3/usb3_vip_cfg.sv"]


@requires_git
def test_change_outside_watched_paths_does_not_stale_a_scoped_capsule(project, store):
    """A capsule that declares its scope is not invalidated by an unrelated
    subsystem's RTL -- but the same change DOES stale an unscoped capsule,
    because an empty watched_paths widens the scope to the whole repo."""
    root, sha = project
    envelope = _ingest_passing_evidence(store, root, sha)
    scoped = gs.record_golden_scenario(store, _capsule(envelope["evidence_id"]))
    unscoped = gs.record_golden_scenario(store, _capsule(
        envelope["evidence_id"], capsule_id="GS-unscoped", watched_paths=[]))

    other = root / "rtl" / "pcie_link"
    other.mkdir(parents=True)
    (other / "pcie_ltssm.v").write_text("module pcie_ltssm(); endmodule\n", encoding="utf-8")
    _commit(root, "unrelated pcie RTL")

    assert gs.evaluate_freshness(root, scoped)["freshness"] == gs.FRESH
    unscoped_result = gs.evaluate_freshness(root, unscoped)
    assert unscoped_result["freshness"] == gs.STALE
    assert unscoped_result["scope"] == "WHOLE_REPO_NO_WATCHED_PATHS_DECLARED"


@requires_git
def test_vip_version_drift_stales_a_capsule_with_no_git_change(project, store):
    root, sha = project
    envelope = _ingest_passing_evidence(store, root, sha)
    capsule = gs.record_golden_scenario(store, _capsule(envelope["evidence_id"]))
    result = gs.evaluate_freshness(root, capsule,
                                   current_vip_versions={"svt_usb": "2025.03"})
    assert result["freshness"] == gs.STALE
    assert result["triggering_changes"] == []
    assert result["vip_version_drift"] == [
        {"tool": "svt_usb", "recorded": "2024.09", "current": "2025.03"}]
    # A tool the caller does not report on is never assumed unchanged-and-fine,
    # but also never invented as drift.
    assert gs.evaluate_freshness(
        root, capsule, current_vip_versions={"svt_usb": "2024.09"})["freshness"] == gs.FRESH


# --- "cannot check" is never FRESH -----------------------------------------


@requires_git
def test_unknown_when_the_recorded_sha_no_longer_resolves(project, store):
    root, sha = project
    envelope = _ingest_passing_evidence(store, root, sha)
    capsule = gs.record_golden_scenario(store, _capsule(
        envelope["evidence_id"], verified_sha="0" * 40))
    result = gs.evaluate_freshness(root, capsule)
    assert result["freshness"] == gs.UNKNOWN
    assert result["diff_status"] == "UNKNOWN_BASE"
    assert any("GIT_HISTORY_UNAVAILABLE" in r for r in result["reasons"])


def test_unknown_outside_a_git_repository(tmp_path):
    capsule = _capsule("EVID-x", verified_sha="deadbeef" * 5)
    result = gs.evaluate_freshness(tmp_path, capsule)
    assert result["freshness"] == gs.UNKNOWN
    assert result["diff_status"] in ("NO_GIT", "UNKNOWN_BASE")


def test_unknown_when_no_sha_was_recorded(tmp_path):
    capsule = _capsule("EVID-x", verified_sha=None)
    result = gs.evaluate_freshness(tmp_path, capsule)
    assert result["freshness"] == gs.UNKNOWN
    assert any("NO_RECORDED_SHA" in r for r in result["reasons"])


def test_version_drift_still_stales_an_unevaluatable_capsule(tmp_path):
    """A capsule whose git history cannot be read but whose VIP moved is
    STALE, not UNKNOWN -- the known-bad fact wins over the unknown one."""
    capsule = _capsule("EVID-x", verified_sha=None)
    result = gs.evaluate_freshness(tmp_path, capsule,
                                   current_vip_versions={"vcs": "2025.06"})
    assert result["freshness"] == gs.STALE


# --- whole-store report + CLI ----------------------------------------------


@requires_git
def test_store_report_takes_the_worst_outcome(project, store):
    root, sha = project
    envelope = _ingest_passing_evidence(store, root, sha)
    gs.record_golden_scenario(store, _capsule(envelope["evidence_id"]))
    gs.record_golden_scenario(store, _capsule(
        envelope["evidence_id"], capsule_id="GS-unresolvable", verified_sha="1" * 40))
    report = gs.evaluate_store_freshness(root, store)
    assert report["status"] == gs.UNKNOWN
    assert report["counts"] == {gs.FRESH: 1, gs.STALE: 0, gs.UNKNOWN: 1}

    rtl = root / "rtl" / "usb3_link" / "usb3_link_ctrl.v"
    rtl.write_text(rtl.read_text(encoding="utf-8") + "// touched\n", encoding="utf-8")
    _commit(root, "rtl touch")
    assert gs.evaluate_store_freshness(root, store)["status"] == gs.STALE


@requires_git
def test_cli_record_then_status_exit_codes(project, store, tmp_path):
    """The real `python -m dv_harness.golden_scenario` entry point, driven as
    a subprocess: record exits 0, status exits 0 while FRESH and 1 once a real
    RTL commit makes the capsule STALE."""
    root, sha = project
    envelope = _ingest_passing_evidence(store, root, sha)
    store.close()  # release the DuckDB file for the subprocess

    capsule_json = tmp_path / "capsule.json"
    capsule_json.write_text(json.dumps(_capsule(envelope["evidence_id"]).to_dict()),
                            encoding="utf-8")

    def run(*args):
        return subprocess.run(
            [sys.executable, "-m", "dv_harness.golden_scenario", *args,
             "--root", str(root)],
            capture_output=True, text=True, timeout=180, encoding="utf-8",
            errors="replace")

    rec = run("record", "--json-file", str(capsule_json))
    assert rec.returncode == 0, rec.stdout + rec.stderr
    assert "recorded golden scenario" in rec.stdout

    ok = run("status")
    assert ok.returncode == 0, ok.stdout + ok.stderr
    assert "GOLDEN SCENARIO FRESHNESS: FRESH" in ok.stdout

    rtl = root / "rtl" / "usb3_link" / "usb3_link_ctrl.v"
    rtl.write_text(rtl.read_text(encoding="utf-8") + "// cli stale\n", encoding="utf-8")
    _commit(root, "rtl change for cli test")

    stale = run("status", "--json")
    assert stale.returncode == 1, stale.stdout + stale.stderr
    payload = json.loads(stale.stdout)
    assert payload["status"] == "STALE"
    assert payload["capsules"][0]["triggering_changes"][0]["path"] == \
        "rtl/usb3_link/usb3_link_ctrl.v"

    listed = run("list")
    assert listed.returncode == 0
    assert TEST_NAME in listed.stdout


def test_read_only_store_predating_the_table_reports_no_capsules(tmp_path):
    """An evidence.duckdb created before `golden_scenarios` existed is opened
    read-only (which skips all schema DDL by design), so the relation really
    is absent. That must read as "nothing recorded", not a CatalogException."""
    db = tmp_path / "old.duckdb"
    with EvidenceStore(db) as s:
        s.query("DROP TABLE golden_scenarios")
    with EvidenceStore(db, read_only=True) as ro:
        assert ro.list_golden_scenarios() == []
        assert ro.get_golden_scenario("GS-anything") is None


def test_cli_status_without_an_evidence_db_is_not_available(tmp_path):
    r = subprocess.run(
        [sys.executable, "-m", "dv_harness.golden_scenario", "status",
         "--root", str(tmp_path)],
        capture_output=True, text=True, timeout=180, encoding="utf-8", errors="replace")
    assert r.returncode == 2
    assert "NOT_AVAILABLE" in r.stdout


# --- qualification_set: category field + completeness (2026-09-06) --------


def _make_capsule(category, *, capsule_id=None, evidence_id="EVID-x"):
    """A minimal in-memory GoldenScenario, no store involved -- used for the
    pure `missing_categories()` tests, which take already-loaded capsules and
    run no query of their own."""
    return gs.GoldenScenario(
        capsule_id=capsule_id or f"GS-fixture-{category}", project="p", subsystem="s",
        test_name="t", evidence_id=evidence_id, category=category)


def test_validate_capsule_rejects_an_unrecognized_category():
    with pytest.raises(gs.CapsuleValidationError):
        gs.validate_capsule(_capsule("EVID-x", category="not_a_real_category"))
    # A category from the real fixed vocabulary is accepted; validate_capsule
    # must not raise for it.
    gs.validate_capsule(_capsule("EVID-x", category="known_pass"))
    # An unset category (the default) is legal too -- category is optional.
    gs.validate_capsule(_capsule("EVID-x", category=None))


def test_capsule_from_json_accepts_a_declared_category():
    data = _capsule("EVID-x", category="timeout").to_dict()
    built = gs.capsule_from_json(data)
    assert built.category == "timeout"


def test_missing_categories_lists_uncovered_categories_in_required_order():
    capsules = [_make_capsule("known_pass"), _make_capsule("timeout"),
                _make_capsule(None, capsule_id="GS-uncategorized")]
    missing = gs.missing_categories(capsules)
    assert missing == [c for c in gs.QUALIFICATION_SET_CATEGORIES
                        if c not in ("known_pass", "timeout")]
    assert "known_pass" not in missing
    assert "timeout" not in missing


def test_missing_categories_empty_when_every_required_category_is_present():
    capsules = [_make_capsule(c) for c in gs.QUALIFICATION_SET_CATEGORIES]
    assert gs.missing_categories(capsules) == []


def test_missing_categories_an_uncategorized_capsule_credits_nothing():
    """A capsule with no declared category (the default) must not be
    silently credited toward ANY required category."""
    capsules = [_make_capsule(None), _make_capsule(None, capsule_id="GS-uncategorized-2")]
    assert gs.missing_categories(capsules, required=("known_pass", "timeout")) == \
        ["known_pass", "timeout"]


def test_missing_categories_ignores_an_out_of_vocabulary_category():
    """A category string outside the fixed vocabulary (a typo, or a stale
    value from before the vocabulary was fixed) must not be credited toward
    a required category it does not name -- it is effectively uncategorized."""
    capsules = [_make_capsule("known_pass"), _make_capsule("made_up_category")]
    missing = gs.missing_categories(capsules, required=("known_pass", "timeout"))
    assert missing == ["timeout"]


def test_missing_categories_respects_a_custom_required_subset():
    capsules = [_make_capsule("register")]
    assert gs.missing_categories(capsules, required=("register", "perf")) == ["perf"]


@requires_git
def test_category_round_trips_through_the_real_store(project, store):
    """A capsule's `category` is not one of `evidence_db.py`'s own known
    columns, so it is persisted through `golden_scenario.py`'s own
    `query()`-based seam -- proved here by recording through the real
    `record_golden_scenario()` and reading it back both singly and via
    `load_golden_scenarios()`, never assuming the in-memory return value
    alone proves persistence."""
    root, sha = project
    envelope = _ingest_passing_evidence(store, root, sha)
    stored = gs.record_golden_scenario(
        store, _capsule(envelope["evidence_id"], category="known_pass"))
    assert stored.category == "known_pass"

    single = gs.load_golden_scenario(store, stored.capsule_id)
    assert single.category == "known_pass"

    all_loaded = gs.load_golden_scenarios(store)
    assert [c.category for c in all_loaded] == ["known_pass"]

    # The existing scalar/json fields are completely unaffected by this
    # addition -- the shape of an already-recorded capsule field is unchanged.
    assert single.verified_sha == sha
    assert single.requirements == ["REQ-USB3-LFPS-001"]


@requires_git
def test_uncategorized_capsule_round_trips_as_none(project, store):
    root, sha = project
    envelope = _ingest_passing_evidence(store, root, sha)
    stored = gs.record_golden_scenario(store, _capsule(envelope["evidence_id"]))
    assert stored.category is None
    assert gs.load_golden_scenario(store, stored.capsule_id).category is None


@requires_git
def test_load_reports_none_category_when_the_column_was_never_added(project, store):
    """A capsule written directly through the store's own
    `insert_golden_scenario()` (bypassing `record_golden_scenario()`, which is
    the only thing that ever adds the `category` column) must still load
    cleanly, with category read as None rather than raising -- the negative
    control proving `_attach_categories()` degrades honestly on a
    `golden_scenarios` table that genuinely never gained the column."""
    root, sha = project
    envelope = _ingest_passing_evidence(store, root, sha)
    capsule = _capsule(envelope["evidence_id"], category="known_pass")
    store.insert_golden_scenario(capsule.to_dict(), evidence_verdict="PASSED")
    loaded = gs.load_golden_scenario(store, capsule.capsule_id)
    assert loaded is not None
    assert loaded.category is None
    assert gs.load_golden_scenarios(store)[0].category is None


def test_qualification_set_report_on_an_empty_store_is_incomplete(tmp_path):
    db = tmp_path / "empty.duckdb"
    with EvidenceStore(db) as s:
        report = gs.qualification_set_report(s)
    assert report["status"] == "INCOMPLETE"
    assert report["missing_categories"] == list(gs.QUALIFICATION_SET_CATEGORIES)
    assert report["capsule_count"] == 0


@requires_git
def test_qualification_set_report_partial_over_a_real_store(project, store):
    root, sha = project
    envelope = _ingest_passing_evidence(store, root, sha)
    gs.record_golden_scenario(store, _capsule(envelope["evidence_id"], category="known_pass"))
    gs.record_golden_scenario(store, _capsule(
        envelope["evidence_id"], capsule_id="GS-timeout-case", category="timeout"))
    gs.record_golden_scenario(store, _capsule(
        envelope["evidence_id"], capsule_id="GS-uncategorized-case"))

    report = gs.qualification_set_report(store)
    assert report["status"] == "INCOMPLETE"
    assert set(report["missing_categories"]) == \
        set(gs.QUALIFICATION_SET_CATEGORIES) - {"known_pass", "timeout"}
    assert report["present_counts"]["known_pass"] == 1
    assert report["present_counts"]["timeout"] == 1
    assert report["present_counts"]["register"] == 0
    assert report["capsule_count"] == 3
    assert report["uncategorized_capsule_count"] == 1


@requires_git
def test_qualification_set_report_complete_when_every_category_is_recorded(project, store):
    root, sha = project
    envelope = _ingest_passing_evidence(store, root, sha)
    for i, category in enumerate(gs.QUALIFICATION_SET_CATEGORIES):
        gs.record_golden_scenario(store, _capsule(
            envelope["evidence_id"], capsule_id=f"GS-cat-{i}", category=category))
    report = gs.qualification_set_report(store)
    assert report["status"] == "COMPLETE"
    assert report["missing_categories"] == []
    assert report["capsule_count"] == len(gs.QUALIFICATION_SET_CATEGORIES)
    assert report["uncategorized_capsule_count"] == 0


@requires_git
def test_cli_qualification_set_reports_missing_then_complete(project, store, tmp_path):
    """The real `qualification-set` CLI verb, driven as a subprocess: exit 1
    with the real missing categories while only some are recorded, exit 0
    once every required category has a real recorded capsule."""
    root, sha = project
    envelope = _ingest_passing_evidence(store, root, sha)
    store.close()  # release the DuckDB file for the subprocess

    def run(*args):
        return subprocess.run(
            [sys.executable, "-m", "dv_harness.golden_scenario", *args,
             "--root", str(root)],
            capture_output=True, text=True, timeout=180, encoding="utf-8",
            errors="replace")

    def record(category, i):
        capsule = _capsule(envelope["evidence_id"], capsule_id=f"GS-cli-cat-{i}",
                           category=category)
        capsule_json = tmp_path / f"capsule_{i}.json"
        capsule_json.write_text(json.dumps(capsule.to_dict()), encoding="utf-8")
        rec = run("record", "--json-file", str(capsule_json))
        assert rec.returncode == 0, rec.stdout + rec.stderr

    for i, category in enumerate(gs.QUALIFICATION_SET_CATEGORIES[:3]):
        record(category, i)

    partial = run("qualification-set", "--json")
    assert partial.returncode == 1, partial.stdout + partial.stderr
    payload = json.loads(partial.stdout)
    assert payload["status"] == "INCOMPLETE"
    assert set(payload["missing_categories"]) == set(gs.QUALIFICATION_SET_CATEGORIES[3:])
    assert "MISSING" not in partial.stdout  # --json means no text rendering

    for i, category in enumerate(gs.QUALIFICATION_SET_CATEGORIES[3:], start=3):
        record(category, i)

    complete = run("qualification-set")
    assert complete.returncode == 0, complete.stdout + complete.stderr
    assert "COMPLETE" in complete.stdout
    assert "every required category has at least one recorded capsule" in complete.stdout


@requires_git
def test_cli_record_rejects_an_unrecognized_category(project, store, tmp_path):
    root, sha = project
    envelope = _ingest_passing_evidence(store, root, sha)
    store.close()
    capsule = _capsule(envelope["evidence_id"], category="totally_made_up")
    capsule_json = tmp_path / "bad_category_capsule.json"
    capsule_json.write_text(json.dumps(capsule.to_dict()), encoding="utf-8")
    r = subprocess.run(
        [sys.executable, "-m", "dv_harness.golden_scenario", "record",
         "--json-file", str(capsule_json), "--root", str(root)],
        capture_output=True, text=True, timeout=180, encoding="utf-8", errors="replace")
    assert r.returncode == 2
    assert "CapsuleValidationError" in r.stdout
