"""VI-1: the Confidence Calibration Engine (`dv_harness/confidence_calibration.py`).

WHAT THESE TESTS ARE FOR. Not "the function returns a dict". The five things
that can actually go wrong with a calibration engine are:

  1. **A calibration fabricated out of too little evidence.** The single most
     expensive failure here would be a confident-looking reliability number
     computed from two records, or -- worse -- a 100% reliability manufactured
     out of ACTIVE records nobody ever re-checked. Both are held: the threshold
     carries a 9-vs-10 negative control, and a tier whose records are all
     ACTIVE-and-never-reconfirmed stays INSUFFICIENT_HISTORY rather than
     reporting a perfect score.
  2. **A detector with no detection power.** A MISCALIBRATED verdict is only
     worth anything if the CALIBRATED verdict is reachable over the same
     machinery, so every positive case here has its negative control: a
     sub-tolerance difference is NOT a finding, DEPRECATED records are NOT
     rejections, and a tier ordering that genuinely holds reports CALIBRATED.
  3. **Outcomes read off the wrong fields.** Every record in this file is
     written by the REAL writers -- `MemoryStore.add()`, `MemoryGC.confirm()`,
     `MemoryGC.retract()`, `MemoryGC.supersede()`, `MemoryGC.deprecate()`,
     `MemoryGC.flag_stale()` -- never by hand-writing a JSON file with the
     fields this module happens to read. A record confirmed and LATER retracted
     is the case that decides whether the ordering rule is real.
  4. **Reading becoming a mutating act.** Asking whether a project is
     calibrated must never create the memory store it is asking about, and must
     never touch a record. Both are asserted against a real on-disk store.
  5. **The tier vocabulary drifting from the two modules that own it.** A tier
     added to `inference.CONFIDENCE_LEVELS` and not here would be silently
     absent from every report.

Nothing here runs a build, a regression, an LSF submission or a stage: the
whole corpus is real MemoryStore records in a throwaway directory, plus one
read-only pass over this repository's own real store.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

from dv_harness import confidence_calibration as cc
from dv_harness.inference import CONFIDENCE_LEVELS
from dv_harness.memory import MemoryGC, MemoryStore
from dv_harness.memory_router import ENGINEERING_ADMISSION_CONFIDENCE_LEVELS

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def root():
    tmp = Path(tempfile.mkdtemp())
    try:
        yield tmp
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------------------------
# helpers -- every record below is written by the REAL memory writers
# --------------------------------------------------------------------------
def add_record(store, tier, *, level="engineering", title="finding"):
    return store.add(level, {"title": title, "protocol": "USB3",
                             "root_cause": f"{title}-rc", "confidence": tier})


def populate(store, tier, *, verified=0, rejected=0, active=0, level="engineering"):
    """`verified` records really confirmed, `rejected` records really retracted,
    `active` records left ACTIVE and never re-checked."""
    gc = MemoryGC(store)
    for i in range(verified):
        rec = add_record(store, tier, level=level, title=f"{tier}-ok-{i}")
        assert gc.confirm(rec["memory_id"], evidence={"note": "independent re-derivation"})
    for i in range(rejected):
        rec = add_record(store, tier, level=level, title=f"{tier}-bad-{i}")
        assert gc.retract(rec["memory_id"], "overturned by current evidence",
                          evidence={"sim_log": "run/sim.log:1201"})
    for i in range(active):
        add_record(store, tier, level=level, title=f"{tier}-open-{i}")


def tier_row(report, tier):
    return report["tiers"][tier]


# --------------------------------------------------------------------------
# 5. the tier vocabulary is owned by inference.py and memory_router.py
# --------------------------------------------------------------------------
def test_calibration_tiers_are_exactly_the_two_owning_modules_vocabulary():
    cc.assert_tiers_cover_inference_levels()
    assert set(cc.CALIBRATION_TIERS) == (
        set(CONFIDENCE_LEVELS) | set(ENGINEERING_ADMISSION_CONFIDENCE_LEVELS))
    # strongest first -- the ordering the whole inversion check rests on
    assert cc.CALIBRATION_TIERS[0] == "CONFIRMED"
    assert cc.TIER_RANK["CONFIRMED"] < cc.TIER_RANK["HIGH"] < cc.TIER_RANK["MEDIUM"] \
        < cc.TIER_RANK["LOW"]


def test_a_tier_invented_here_or_dropped_from_inference_fails_loudly(monkeypatch):
    monkeypatch.setattr(cc, "CALIBRATION_TIERS", ("HIGH", "MEDIUM", "LOW"))
    with pytest.raises(AssertionError):
        cc.assert_tiers_cover_inference_levels()
    monkeypatch.setattr(cc, "CALIBRATION_TIERS",
                        ("CONFIRMED", "HIGH", "MEDIUM", "LOW", "ABSOLUTE"))
    with pytest.raises(AssertionError):
        cc.assert_tiers_cover_inference_levels()


def test_every_cited_definition_and_outcome_source_resolves():
    assert cc.assert_tier_sources_resolvable() == cc.TIER_DEFINITION_SOURCE
    # the citations are real symbols, not decoration
    assert cc._resolve_symbol("dv_harness.memory:MemoryGC.confirm").__name__ == "confirm"


def test_a_renamed_outcome_writer_is_caught(monkeypatch):
    monkeypatch.setitem(cc.OUTCOME_SOURCE, cc.OUTCOME_VERIFIED,
                        "dv_harness.memory:MemoryGC.reconfirm_everything")
    with pytest.raises(AssertionError):
        cc.assert_tier_sources_resolvable()


# --------------------------------------------------------------------------
# 4. reading is never a mutating act
# --------------------------------------------------------------------------
def test_a_project_with_no_memory_store_is_not_available_and_stays_untouched(root):
    report = cc.calibrate(root)
    assert report["status"] == cc.STATUS_NOT_AVAILABLE
    assert report["reason"] == "NO_MEMORY_STORE"
    assert report["uncalibratable_tiers"] == list(cc.CALIBRATION_TIERS)
    assert len(report["next_best_actions"]) == len(cc.CALIBRATION_TIERS)
    # MemoryStore.__init__ would have mkdir'd the tree and written index.json;
    # merely asking whether a project is calibrated must not create the store.
    assert not (root / ".dv-harness").exists()
    assert list(root.iterdir()) == []


def test_calibrating_a_real_store_changes_no_file(root):
    store = MemoryStore(root)
    populate(store, "HIGH", verified=4, rejected=2, active=3)
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns)
              for p in sorted((root / ".dv-harness").rglob("*")) if p.is_file()}
    time.sleep(0.01)
    cc.calibrate(root)
    after = {p: (p.read_bytes(), p.stat().st_mtime_ns)
             for p in sorted((root / ".dv-harness").rglob("*")) if p.is_file()}
    assert before == after


# --------------------------------------------------------------------------
# 1. no calibration is fabricated out of too little evidence
# --------------------------------------------------------------------------
def test_records_with_no_recognized_tier_are_never_mapped_onto_one(root):
    store = MemoryStore(root)
    for i in range(5):
        store.add("project", {"title": f"note-{i}"})  # add() defaults confidence to UNKNOWN
    report = cc.calibrate(root)
    assert report["status"] == cc.STATUS_NOT_AVAILABLE
    assert report["reason"] == "NO_RECORD_CARRIES_A_CONFIDENCE_TIER"
    assert report["corpus"]["records_scanned"] == 5
    assert report["corpus"]["records_with_recognized_tier"] == 0
    assert report["corpus"]["records_without_recognized_tier"] == {"UNKNOWN": 5}


def test_active_never_rechecked_records_never_manufacture_a_reliability(root):
    store = MemoryStore(root)
    populate(store, "HIGH", active=40)
    report = cc.calibrate(root)
    assert report["status"] == cc.STATUS_INSUFFICIENT_HISTORY
    row = tier_row(report, "HIGH")
    assert row["records"] == 40
    assert row["determinate"] == 0
    assert row["observed_reliability"] is None
    assert row["outcome_reasons"] == {cc.INDETERMINATE_NEVER_RECHECKED: 40}


def test_nine_determinate_outcomes_is_still_insufficient_ten_is_not(root):
    """The threshold's negative control -- without it, `MIN_DETERMINATE_OUTCOMES_
    PER_TIER` could be any number and no test would notice."""
    nine = Path(tempfile.mkdtemp())
    ten = Path(tempfile.mkdtemp())
    try:
        populate(MemoryStore(nine), "HIGH", verified=8, rejected=1)
        populate(MemoryStore(ten), "HIGH", verified=9, rejected=1)
        assert cc.calibrate(nine)["status"] == cc.STATUS_INSUFFICIENT_HISTORY
        assert tier_row(cc.calibrate(nine), "HIGH")["calibratable"] is False
        ten_report = cc.calibrate(ten)
        assert ten_report["status"] == cc.STATUS_CALIBRATED
        assert tier_row(ten_report, "HIGH")["observed_reliability"] == pytest.approx(0.9)
    finally:
        shutil.rmtree(nine, ignore_errors=True)
        shutil.rmtree(ten, ignore_errors=True)


def test_insufficient_history_names_every_uncalibratable_tier_with_a_real_action(root):
    store = MemoryStore(root)
    populate(store, "HIGH", verified=2, rejected=1)
    report = cc.calibrate(root)
    assert report["status"] == cc.STATUS_INSUFFICIENT_HISTORY
    assert report["uncalibratable_tiers"] == list(cc.CALIBRATION_TIERS)
    # produced by the REAL inference.next_best_action() through its catalog
    gaps = {a["gap"] for a in report["next_best_actions"]}
    assert gaps == {f"tier_{t}_insufficient_history" for t in cc.CALIBRATION_TIERS}
    assert all(a["source"] == "confidence_calibration" for a in report["next_best_actions"])


# --------------------------------------------------------------------------
# 3. outcomes are read off the fields the real writers set
# --------------------------------------------------------------------------
def test_a_confirmed_then_retracted_record_is_a_rejected_outcome(root):
    store = MemoryStore(root)
    gc = MemoryGC(store)
    rec = add_record(store, "HIGH", title="held-then-overturned")
    assert gc.confirm(rec["memory_id"], evidence={"note": "second run agreed"})
    assert gc.retract(rec["memory_id"], "later waveform contradicted it")
    stored = store.get(rec["memory_id"])
    assert stored["confirmation_count"] == 1 and stored["status"] == "RETRACTED"
    verdict = cc.classify_record_outcome(stored)
    assert verdict["outcome"] == cc.OUTCOME_REJECTED
    assert verdict["reason"] == "RETRACTED"
    assert verdict["confirmation_count"] == 1


def test_supersede_is_a_rejection_carrying_its_own_distinct_reason(root):
    store = MemoryStore(root)
    gc = MemoryGC(store)
    old = add_record(store, "CONFIRMED", title="first-answer")
    new = add_record(store, "CONFIRMED", title="corrected-answer")
    assert gc.supersede(old["memory_id"], new["memory_id"], "better evidence")
    verdict = cc.classify_record_outcome(store.get(old["memory_id"]))
    assert verdict["outcome"] == cc.OUTCOME_REJECTED
    assert verdict["reason"] == "SUPERSEDED"


def test_deprecated_and_stale_records_are_indeterminate_not_rejections(root):
    """The negative control that stops a retired knowledge base from reading as
    a catastrophically miscalibrated one: ten DEPRECATED records must not make a
    tier calibratable at 0% reliability."""
    store = MemoryStore(root)
    gc = MemoryGC(store)
    for i in range(10):
        rec = add_record(store, "HIGH", title=f"retired-{i}")
        assert gc.deprecate(rec["memory_id"], "environment retired")
    stale = add_record(store, "HIGH", title="aged-out")
    assert gc.flag_stale(stale["memory_id"], "past knowledge_center.max_age_days")
    report = cc.calibrate(root)
    row = tier_row(report, "HIGH")
    assert row["rejected"] == 0
    assert row["determinate"] == 0
    assert row["calibratable"] is False
    assert row["outcome_reasons"] == {"RETIRED_NOT_REFUTED": 10,
                                      "FLAGGED_STALE_NOT_YET_RECHECKED": 1}
    assert report["status"] == cc.STATUS_INSUFFICIENT_HISTORY


def test_a_revalidated_record_becomes_a_verified_outcome(root):
    """MemoryGC.confirm() restores a NEEDS_REVALIDATION record to ACTIVE -- the
    outcome classifier must follow that, not the stale flag."""
    store = MemoryStore(root)
    gc = MemoryGC(store)
    rec = add_record(store, "MEDIUM", title="stale-then-reconfirmed")
    assert gc.flag_stale(rec["memory_id"], "aged")
    assert cc.classify_record_outcome(store.get(rec["memory_id"]))["outcome"] == \
        cc.OUTCOME_INDETERMINATE
    assert gc.confirm(rec["memory_id"], evidence={"note": "re-derived"})
    verdict = cc.classify_record_outcome(store.get(rec["memory_id"]))
    assert verdict["outcome"] == cc.OUTCOME_VERIFIED
    assert verdict["reason"] == "INDEPENDENTLY_RECONFIRMED"


def test_outcomes_are_counted_per_memory_level(root):
    store = MemoryStore(root)
    populate(store, "HIGH", verified=3, level="engineering")
    populate(store, "HIGH", verified=2, level="working")
    row = tier_row(cc.calibrate(root), "HIGH")
    assert row["levels"] == {"engineering": 3, "working": 2}


# --------------------------------------------------------------------------
# 2. the detector has real detection power
# --------------------------------------------------------------------------
def test_a_higher_tier_holding_up_less_often_is_a_real_inversion(root):
    store = MemoryStore(root)
    populate(store, "HIGH", verified=3, rejected=7)      # 30%
    populate(store, "MEDIUM", verified=9, rejected=1)    # 90%
    report = cc.calibrate(root)
    assert report["status"] == cc.STATUS_MISCALIBRATED
    inversions = [f for f in report["findings"]
                  if f["kind"] == cc.FINDING_INVERTED_TIER_ORDER]
    assert len(inversions) == 1
    found = inversions[0]
    assert (found["higher_tier"], found["lower_tier"]) == ("HIGH", "MEDIUM")
    assert found["higher_observed_reliability"] == pytest.approx(0.3)
    assert found["lower_observed_reliability"] == pytest.approx(0.9)
    assert "do not support treating HIGH as stronger than MEDIUM" in found["detail"]
    actions = {a["gap"]: a["suggested_action"] for a in report["next_best_actions"]}
    assert cc.FINDING_INVERTED_TIER_ORDER in actions
    assert "treat the higher tier as no stronger" in actions[cc.FINDING_INVERTED_TIER_ORDER]


def test_the_same_machinery_reports_calibrated_when_the_ordering_holds(root):
    """The positive control for the test above. Without it, a module that
    returned MISCALIBRATED unconditionally would pass."""
    store = MemoryStore(root)
    populate(store, "HIGH", verified=9, rejected=1)      # 90%
    populate(store, "MEDIUM", verified=5, rejected=5)    # 50%
    populate(store, "LOW", verified=2, rejected=8)       # 20%
    report = cc.calibrate(root)
    assert report["status"] == cc.STATUS_CALIBRATED
    assert report["findings"] == []
    assert report["calibratable_tiers"] == ["HIGH", "MEDIUM", "LOW"]
    assert report["uncalibratable_tiers"] == ["CONFIRMED"]


def test_a_sub_tolerance_difference_is_not_reported_as_an_inversion(root):
    """8/10 under 9/10 is exactly one resolution band apart -- inside the noise
    this report can measure, so it must not be a finding."""
    store = MemoryStore(root)
    populate(store, "HIGH", verified=8, rejected=2)      # 80%
    populate(store, "MEDIUM", verified=9, rejected=1)    # 90%
    report = cc.calibrate(root)
    assert report["findings"] == []
    assert report["status"] == cc.STATUS_CALIBRATED
    # and one more record's worth of separation IS reported
    populate(store, "MEDIUM", verified=10)               # -> 19/20 = 95%
    assert cc.calibrate(root)["status"] == cc.STATUS_MISCALIBRATED


def test_a_non_adjacent_inversion_is_still_found(root):
    """CONFIRMED below LOW is a real inversion even when the two tiers between
    them look individually fine -- adjacent-pairs-only comparison would miss it."""
    store = MemoryStore(root)
    populate(store, "CONFIRMED", verified=2, rejected=8)   # 20%
    populate(store, "HIGH", verified=3, rejected=7)        # 30%
    populate(store, "MEDIUM", verified=4, rejected=6)      # 40%
    populate(store, "LOW", verified=9, rejected=1)         # 90%
    report = cc.calibrate(root)
    pairs = {(f["higher_tier"], f["lower_tier"]) for f in report["findings"]
             if f["kind"] == cc.FINDING_INVERTED_TIER_ORDER}
    assert ("CONFIRMED", "LOW") in pairs
    assert ("CONFIRMED", "HIGH") not in pairs   # 20% vs 30% is inside tolerance
    assert ("HIGH", "LOW") in pairs


def test_an_uncalibratable_tier_is_never_used_in_an_inversion(root):
    """A tier with 1 determinate outcome at 0% must not drag a well-evidenced
    tier into a fabricated finding."""
    store = MemoryStore(root)
    populate(store, "CONFIRMED", rejected=1)             # 0% over ONE outcome
    populate(store, "HIGH", verified=9, rejected=1)      # 90% over ten
    report = cc.calibrate(root)
    assert report["findings"] == []
    assert report["status"] == cc.STATUS_CALIBRATED
    assert tier_row(report, "CONFIRMED")["observed_reliability"] is None


# --------------------------------------------------------------------------
# declared floors: opt-in, validated, and absent-with-a-reason by default
# --------------------------------------------------------------------------
def test_no_tier_carries_a_declared_floor_by_default_and_every_one_says_why(root):
    store = MemoryStore(root)
    populate(store, "HIGH", verified=5, rejected=5)
    report = cc.calibrate(root)
    for tier in cc.CALIBRATION_TIERS:
        row = tier_row(report, tier)
        assert row["declared_floor"] is None
        assert "no numeric reliability is declared" in row["declared_floor_basis"]
        assert "stated success rate" in row["declared_floor_basis"]


def test_a_declared_floor_a_tier_falls_below_is_a_finding(root):
    store = MemoryStore(root)
    populate(store, "HIGH", verified=5, rejected=5)      # 50%
    cfg = {"confidence_calibration": {"tier_reliability_floor": {"HIGH": 0.8}}}
    report = cc.calibrate(root, cfg=cfg)
    assert report["status"] == cc.STATUS_MISCALIBRATED
    below = [f for f in report["findings"] if f["kind"] == cc.FINDING_BELOW_DECLARED_FLOOR]
    assert len(below) == 1
    assert below[0]["tier"] == "HIGH"
    assert below[0]["declared_floor"] == 0.8
    # and the same store under a floor it clears is CALIBRATED
    ok = cc.calibrate(root, cfg={"confidence_calibration":
                                 {"tier_reliability_floor": {"HIGH": 0.4}}})
    assert ok["status"] == cc.STATUS_CALIBRATED


def test_a_floor_on_an_uncalibratable_tier_never_fires(root):
    store = MemoryStore(root)
    populate(store, "LOW", verified=0, rejected=2)
    report = cc.calibrate(root, cfg={"confidence_calibration":
                                     {"tier_reliability_floor": {"LOW": 0.9}}})
    assert report["findings"] == []
    assert report["status"] == cc.STATUS_INSUFFICIENT_HISTORY


@pytest.mark.parametrize("block,reason", [
    ({"tier_reliability_floor": {"VERY_HIGH": 0.9}}, "UNKNOWN_CALIBRATION_TIER"),
    ({"tier_reliability_floor": {"HIGH": 1.5}}, "TIER_RELIABILITY_FLOOR_OUT_OF_RANGE"),
    ({"tier_reliability_floor": {"HIGH": "most of the time"}},
     "TIER_RELIABILITY_FLOOR_NOT_A_NUMBER"),
    ({"tier_reliability_floor": [0.9]}, "TIER_RELIABILITY_FLOOR_NOT_A_DICT"),
])
def test_a_malformed_floor_is_refused_never_silently_ignored(block, reason):
    with pytest.raises(cc.CalibrationConfigError) as exc:
        cc.resolve_config({"confidence_calibration": block})
    assert exc.value.reason == reason


def test_resolve_config_fills_every_tier_and_accepts_a_real_floor():
    conf = cc.resolve_config({"confidence_calibration":
                              {"tier_reliability_floor": {"high": 0.75}}})
    assert set(conf["tier_reliability_floor"]) == set(cc.CALIBRATION_TIERS)
    assert conf["tier_reliability_floor"]["HIGH"] == 0.75
    assert conf["tier_reliability_floor"]["LOW"] is None


# --------------------------------------------------------------------------
# corpus honesty: index drift is surfaced, not silently shrunk
# --------------------------------------------------------------------------
def test_a_record_file_with_no_index_row_is_reported_as_drift(root):
    store = MemoryStore(root)
    populate(store, "HIGH", verified=1)
    orphan = store.dir / "engineering" / "MEM-ORPHAN0001.json"
    orphan.write_text(json.dumps({"memory_id": "MEM-ORPHAN0001", "level": "engineering",
                                  "confidence": "HIGH", "status": "ACTIVE"}),
                      encoding="utf-8")
    report = cc.calibrate(root)
    assert report["corpus"]["index_integrity_ok"] is False
    assert report["corpus"]["record_files_missing_from_index"] == 1
    # the orphan is genuinely NOT counted -- the drift line is how a reader knows
    assert tier_row(report, "HIGH")["records"] == 1


# --------------------------------------------------------------------------
# front door
# --------------------------------------------------------------------------
def test_execute_verb_exit_codes_and_unknown_verb(root):
    store = MemoryStore(root)
    populate(store, "HIGH", verified=9, rejected=1)
    code, payload = cc.execute_verb(root, "report")
    assert code == 0 and payload["status"] == cc.STATUS_CALIBRATED
    populate(store, "MEDIUM", verified=10)      # 100%
    populate(store, "HIGH", rejected=5)         # 9/15 = 60% -- a real inversion
    code, _ = cc.execute_verb(root, "report")
    assert code == 2
    code, text = cc.execute_verb(root, "show")
    assert code == 2 and isinstance(text, str)
    code, payload = cc.execute_verb(root, "tiers")
    assert code == 0 and payload["tier_order"] == list(cc.CALIBRATION_TIERS)
    code, payload = cc.execute_verb(root, "calibrate-everything")
    assert code == 1 and payload["error"] == "UNKNOWN_VERB"


def test_rendered_report_always_prints_every_tier_including_empty_ones(root):
    store = MemoryStore(root)
    populate(store, "HIGH", verified=9, rejected=1)
    text = cc.render_report_text(cc.calibrate(root))
    for tier in cc.CALIBRATION_TIERS:
        assert tier in text
    assert "90%" in text


def test_module_front_door_runs_as_a_real_subprocess(root):
    store = MemoryStore(root)
    populate(store, "HIGH", verified=3, rejected=7)
    populate(store, "MEDIUM", verified=9, rejected=1)
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.confidence_calibration", "show",
         "--project-root", str(root)],
        cwd=str(ROOT), capture_output=True, text=True)
    assert proc.returncode == 2, proc.stderr
    assert "MISCALIBRATED" in proc.stdout
    assert cc.FINDING_INVERTED_TIER_ORDER in proc.stdout


# --------------------------------------------------------------------------
# no human-approval gate is referenced, let alone weakened
# --------------------------------------------------------------------------
def test_the_module_touches_no_approval_or_governance_symbol():
    src = (ROOT / "dv_harness" / "confidence_calibration.py").read_text(encoding="utf-8")
    code = "\n".join(line for line in src.splitlines()
                     if not line.lstrip().startswith("#"))
    for forbidden in ("ControlPlane", "can_signoff", "assert_human_approval",
                      "HumanApprovalRequiredError", "ProductionWriteNotAuthorizedError",
                      "approve(", "subprocess", "os.system"):
        assert forbidden not in code, forbidden


def test_the_module_never_writes_to_the_memory_store():
    """Checked against the module's real AST, not its text: a mutating METHOD
    CALL is what would matter, and prose naming `MemoryGC.confirm()` in a
    docstring is not one."""
    import ast
    tree = ast.parse((ROOT / "dv_harness" / "confidence_calibration.py")
                     .read_text(encoding="utf-8"))
    mutating = {"add", "confirm", "retract", "supersede", "deprecate", "flag_stale",
                "mark_used", "reindex", "write_text", "write_bytes", "mkdir", "unlink",
                "event", "approve"}
    called = {node.func.attr for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    assert not (called & mutating), sorted(called & mutating)


# --------------------------------------------------------------------------
# this repository's own real history
# --------------------------------------------------------------------------
def test_this_repos_own_store_reports_an_honest_state_not_a_fabricated_one():
    """Measured 2026-09-05 against this project's REAL store: 92 records
    scanned, 46 carrying a tier, and exactly ONE determinate outcome in the
    whole history (one CONFIRMED record with a real confirmation, zero
    retractions) -- so the honest answer is INSUFFICIENT_HISTORY, and this test
    exists to make sure the engine says so instead of reporting a 100%
    reliability off a single record.

    Read-only: this asserts against the live store without writing to it."""
    if not (ROOT / ".dv-harness" / "memory" / "index.json").exists():
        pytest.skip("this checkout has no memory store")
    report = cc.calibrate(ROOT)
    assert report["status"] in (cc.STATUS_NOT_AVAILABLE, cc.STATUS_INSUFFICIENT_HISTORY)
    assert report["findings"] == []
    if report["status"] == cc.STATUS_INSUFFICIENT_HISTORY:
        assert report["corpus"]["records_with_recognized_tier"] > 0
        assert all(tier_row(report, t)["observed_reliability"] is None
                   for t in cc.CALIBRATION_TIERS)
        # internal consistency: every scanned record is either tiered or counted
        # as untiered -- a corpus that loses records would understate history
        untiered = sum(report["corpus"]["records_without_recognized_tier"].values())
        assert (report["corpus"]["records_with_recognized_tier"] + untiered
                == report["corpus"]["records_scanned"])


# --------------------------------------------------------------------------
# Confidence-Calibration Feedback Loop: draft_reweighted_confidence_proposal()
# --------------------------------------------------------------------------
def test_score_confidence_constants_self_check_passes_against_the_real_formula():
    """The self-check this module runs at import must also be callable on
    demand and must pass against the real, unmodified inference.score_confidence()."""
    cc.assert_score_confidence_constants_current()   # must not raise


def test_a_drifted_constant_is_caught_loudly(monkeypatch):
    """The same detection-power discipline
    test_a_tier_invented_here_or_dropped_from_inference_fails_loudly() already
    holds one level up: a constant that no longer describes the real formula
    must fail LOUDLY, not silently produce a wrong proposal."""
    monkeypatch.setitem(cc.SCORE_CONFIDENCE_CONSTANTS, "high_threshold", 99)
    with pytest.raises(AssertionError):
        cc.assert_score_confidence_constants_current()


def test_no_inversion_drafts_no_proposal(root):
    """Negative control: a CALIBRATED report (or one with no
    INVERTED_TIER_ORDER finding at all) must never fabricate a re-weighting
    proposal out of nothing."""
    store = MemoryStore(root)
    populate(store, "HIGH", verified=9, rejected=1)      # 90%
    populate(store, "MEDIUM", verified=5, rejected=5)     # 50%
    report = cc.calibrate(root)
    assert report["status"] == cc.STATUS_CALIBRATED

    proposal = cc.draft_reweighted_confidence_proposal(report)
    assert proposal["status"] == cc.REWEIGHT_PROPOSAL_NO_INVERSION
    assert proposal["proposed_constants"] is None
    assert proposal["changed_constants"] == []
    assert proposal["current_constants"] == cc.SCORE_CONFIDENCE_CONSTANTS


def test_a_high_over_medium_inversion_drafts_a_tightened_high_threshold(root):
    """The real, worked example: HIGH holding up materially less often than
    MEDIUM proposes tightening HIGH's own entry bar by exactly one
    source_weight -- never a live change, never applied here."""
    store = MemoryStore(root)
    populate(store, "HIGH", verified=3, rejected=7)       # 30%
    populate(store, "MEDIUM", verified=9, rejected=1)     # 90%
    report = cc.calibrate(root)
    assert report["status"] == cc.STATUS_MISCALIBRATED

    # Never a live code change: drafting a proposal writes nothing at all --
    # snapshotted around the ONE call this test is actually about.
    before = sorted((root / ".dv-harness").rglob("*"))
    proposal = cc.draft_reweighted_confidence_proposal(report)
    after = sorted((root / ".dv-harness").rglob("*"))
    assert before == after
    inference_src_before = (Path(cc.__file__).parent / "inference.py").read_bytes()

    assert proposal["status"] == cc.REWEIGHT_PROPOSAL_DRAFTED
    assert len(proposal["changed_constants"]) == 1
    entry = proposal["changed_constants"][0]
    assert entry["constant"] == "high_threshold"
    assert entry["current_value"] == cc.SCORE_CONFIDENCE_CONSTANTS["high_threshold"]
    assert entry["proposed_value"] == (
        cc.SCORE_CONFIDENCE_CONSTANTS["high_threshold"]
        + cc.SCORE_CONFIDENCE_CONSTANTS["source_weight"])
    assert entry["delta"] == cc.SCORE_CONFIDENCE_CONSTANTS["source_weight"]
    assert len(entry["cited_findings"]) == 1
    assert entry["cited_findings"][0]["higher_tier"] == "HIGH"
    assert entry["cited_findings"][0]["lower_tier"] == "MEDIUM"

    # Only the ONE cited constant moved; everything else is untouched.
    proposed = proposal["proposed_constants"]
    for name, value in proposal["current_constants"].items():
        if name != "high_threshold":
            assert proposed[name] == value

    assert proposal["addressable_inversions"] == [proposal["changed_constants"][0]["cited_findings"][0]]
    assert proposal["unaddressable_inversions"] == []
    assert "DATA PROPOSAL ONLY" in proposal["disclosure"]
    assert "never" in proposal["disclosure"].lower()
    assert "capability_evolution" in proposal["disclosure"]

    # inference.py's own real file on disk is byte-for-byte unchanged.
    assert (Path(cc.__file__).parent / "inference.py").read_bytes() == inference_src_before


def test_a_medium_over_low_inversion_tightens_medium_threshold(root):
    store = MemoryStore(root)
    populate(store, "HIGH", verified=9, rejected=1)       # 90%, holds fine
    populate(store, "MEDIUM", verified=3, rejected=7)     # 30%
    populate(store, "LOW", verified=9, rejected=1)        # 90%
    report = cc.calibrate(root)
    assert report["status"] == cc.STATUS_MISCALIBRATED

    proposal = cc.draft_reweighted_confidence_proposal(report)
    assert proposal["status"] == cc.REWEIGHT_PROPOSAL_DRAFTED
    names = {e["constant"] for e in proposal["changed_constants"]}
    assert names == {"medium_threshold"}
    entry = proposal["changed_constants"][0]
    assert entry["proposed_value"] == (
        cc.SCORE_CONFIDENCE_CONSTANTS["medium_threshold"]
        + cc.SCORE_CONFIDENCE_CONSTANTS["source_weight"])


def test_two_findings_on_the_same_constant_bump_it_only_once(root):
    """HIGH underperforming BOTH MEDIUM and LOW produces two real
    INVERTED_TIER_ORDER findings that both name HIGH as the over-ranked tier.
    They must tighten high_threshold ONCE, citing both -- never sum the bumps,
    which would manufacture a bigger change than any one finding alone
    supports."""
    store = MemoryStore(root)
    populate(store, "HIGH", verified=3, rejected=7)       # 30%
    populate(store, "MEDIUM", verified=9, rejected=1)     # 90%
    populate(store, "LOW", verified=10, rejected=0)       # 100%
    report = cc.calibrate(root)
    pairs = {(f["higher_tier"], f["lower_tier"]) for f in report["findings"]
             if f["kind"] == cc.FINDING_INVERTED_TIER_ORDER}
    assert ("HIGH", "MEDIUM") in pairs and ("HIGH", "LOW") in pairs

    proposal = cc.draft_reweighted_confidence_proposal(report)
    assert proposal["status"] == cc.REWEIGHT_PROPOSAL_DRAFTED
    assert len(proposal["changed_constants"]) == 1
    entry = proposal["changed_constants"][0]
    assert entry["constant"] == "high_threshold"
    assert entry["proposed_value"] == (
        cc.SCORE_CONFIDENCE_CONSTANTS["high_threshold"]
        + cc.SCORE_CONFIDENCE_CONSTANTS["source_weight"])   # ONE bump, not two
    assert len(entry["cited_findings"]) == 2


def test_confirmed_only_inversion_is_reported_not_addressable(root):
    """CONFIRMED is minted by MemoryConsolidator.from_closed_finding() behind a
    procedural bar, never by score_confidence()'s formula -- so an inversion
    naming ONLY CONFIRMED as over-ranked must never draft a proposal that
    could not possibly fix what it cites."""
    store = MemoryStore(root)
    populate(store, "CONFIRMED", verified=2, rejected=8)   # 20%
    populate(store, "HIGH", verified=9, rejected=1)        # 90%
    report = cc.calibrate(root)
    inversions = [f for f in report["findings"] if f["kind"] == cc.FINDING_INVERTED_TIER_ORDER]
    assert len(inversions) == 1 and inversions[0]["higher_tier"] == "CONFIRMED"

    proposal = cc.draft_reweighted_confidence_proposal(report)
    assert proposal["status"] == cc.REWEIGHT_PROPOSAL_NOT_ADDRESSABLE
    assert proposal["proposed_constants"] is None
    assert proposal["changed_constants"] == []
    assert len(proposal["unaddressable_inversions"]) == 1
    assert proposal["unaddressable_inversions"][0]["higher_tier"] == "CONFIRMED"
    assert "CONFIRMED" in proposal["reason"]
    assert "procedural bar" in proposal["reason"]


def test_a_mixed_report_drafts_a_proposal_and_still_names_the_unaddressable_ones(root):
    """CONFIRMED-over-LOW (unaddressable) alongside HIGH-over-MEDIUM
    (addressable) in the SAME report: the proposal is still drafted from the
    addressable finding, and the unaddressable one is carried, not dropped."""
    store = MemoryStore(root)
    populate(store, "CONFIRMED", verified=2, rejected=8)   # 20%
    populate(store, "HIGH", verified=3, rejected=7)        # 30%
    populate(store, "LOW", verified=9, rejected=1)         # 90%
    # MEDIUM deliberately left uncalibrated (no records), so the only two
    # findings are CONFIRMED>LOW (unaddressable) and HIGH>LOW (addressable) --
    # nothing else muddies which constants this test expects to move.
    report = cc.calibrate(root)
    findings = [f for f in report["findings"] if f["kind"] == cc.FINDING_INVERTED_TIER_ORDER]
    pairs = {(f["higher_tier"], f["lower_tier"]) for f in findings}
    assert pairs == {("CONFIRMED", "LOW"), ("HIGH", "LOW")}

    proposal = cc.draft_reweighted_confidence_proposal(report)
    assert proposal["status"] == cc.REWEIGHT_PROPOSAL_DRAFTED
    addressable_pairs = {(f["higher_tier"], f["lower_tier"]) for f in proposal["addressable_inversions"]}
    unaddressable_pairs = {(f["higher_tier"], f["lower_tier"]) for f in proposal["unaddressable_inversions"]}
    assert ("HIGH", "LOW") in addressable_pairs
    assert ("CONFIRMED", "LOW") in unaddressable_pairs
    assert {e["constant"] for e in proposal["changed_constants"]} == {"high_threshold"}


def test_medium_threshold_never_crosses_high_threshold(monkeypatch, root):
    """A disclosed, real clamp rather than a silent numeric fudge: if bumping
    medium_threshold would put it at or above the proposed high_threshold, it
    is clamped to stay strictly below, and the clamp is recorded."""
    monkeypatch.setitem(cc.SCORE_CONFIDENCE_CONSTANTS, "medium_threshold", 5)
    monkeypatch.setitem(cc.SCORE_CONFIDENCE_CONSTANTS, "high_threshold", 6)
    # assert_score_confidence_constants_current() would now fail against the
    # real formula, so build a report by hand rather than calling calibrate()
    # against these hypothetical constants -- this test is about the CLAMP
    # arithmetic, not about re-deriving a real inversion under altered
    # constants.
    finding = {
        "kind": cc.FINDING_INVERTED_TIER_ORDER,
        "higher_tier": "MEDIUM", "lower_tier": "LOW",
        "higher_observed_reliability": 0.3, "lower_observed_reliability": 0.9,
        "margin": 0.6, "tolerance": 0.1,
        "detail": "MEDIUM held up 30% ... LOW held up 90% ...",
    }
    monkeypatch.setattr(cc, "assert_score_confidence_constants_current", lambda: None)
    proposal = cc.draft_reweighted_confidence_proposal({"findings": [finding]})
    assert proposal["status"] == cc.REWEIGHT_PROPOSAL_DRAFTED
    entry = next(e for e in proposal["changed_constants"] if e["constant"] == "medium_threshold")
    assert entry.get("clamped") is True
    assert entry["proposed_value"] < proposal["proposed_constants"]["high_threshold"]
    assert proposal["proposed_constants"]["medium_threshold"] < proposal["proposed_constants"]["high_threshold"]


def test_draft_proposal_re_runs_the_constants_self_check(monkeypatch):
    """A drifted constant must be caught even when a caller only calls
    draft_reweighted_confidence_proposal() directly, never the import-time
    check on its own."""
    monkeypatch.setitem(cc.SCORE_CONFIDENCE_CONSTANTS, "counter_evidence_penalty", 1)
    with pytest.raises(AssertionError):
        cc.draft_reweighted_confidence_proposal({"findings": []})
