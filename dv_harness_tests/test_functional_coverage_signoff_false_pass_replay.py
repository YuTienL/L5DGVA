"""Known-Governance-Failure Replay fixture -- migrated from Parent (M5
Cohort 5, CAP-M5-COV-001).

REAL DOCUMENTED INCIDENT, per Parent's own audit finding (this module's
own provenance note, since canonical does not carry Parent's
`.dv-harness/l5dgva_audit_result_E.md` audit-program artifact): before
`classify_coverage_kind()` existed, this project's own evidence database
carried code-coverage categories (VCS `-cm`'s fixed `line`/`cond`/`fsm`/
`tgl`/`branch` metric names) and functional-coverage bins in the SAME
`coverage_samples` table with no `kind` column -- so a project whose
recorded evidence happened to be ONLY a pure code-coverage category at a
high percent (e.g. "line" at 100%) would have that number silently
credited as functional-coverage closure, reaching
`FUNCTIONAL_COVERAGE_SIGNOFF_READY = True` with zero functional coverage
ever measured. That is a real "status false PASS" failure class.

WHY THIS FILE EXISTS ALONGSIDE AN ALREADY-PASSING BEHAVIOURAL TEST.
`dv_harness_tests/test_functional_coverage_signoff.py::
test_code_coverage_alone_never_masquerades_as_functional_signoff_ready`
already asserts the CURRENT (fixed) module gives the right answer on this
exact fixture. Per this project's REUSE-before-EXTEND-before-ADD
discipline, this file does not duplicate that assertion. What it adds is
the one thing that existing test cannot show on its own: a REPLAY --
proof, on the real production code path, that reverting the fix
(monkeypatching `classify_coverage_kind` back to the pre-fix behaviour --
every category counted functional) reproduces the EXACT documented false
PASS over the SAME minimal fixture. That is what makes this a
governance-failure REPLAY fixture rather than an ordinary unit test: it
demonstrates the incident is real and mechanically reproducible through
`functional_coverage_signoff.py`'s own `ca.classify_coverage_kind(n)` call
site (module-attribute lookup at call time, hence the `monkeypatch.setattr
(ca, ...)` below actually reaches it), not merely that today's code happens
to return the right value.
"""
from __future__ import annotations

from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")

from dv_harness import coverage_analysis as ca
from dv_harness import functional_coverage_signoff as fcs
from dv_harness.evidence_db import EvidenceStore, default_db_path


def _insert_coverage(root: Path, categories) -> None:
    with EvidenceStore(default_db_path(root)) as store:
        for cat in categories:
            store.insert_coverage_sample(cat, timestamp="2026-09-16T00:00:00Z", source="test")


# The exact minimal shape the real audit finding describes: the evidence
# database has recorded ONLY a pure VCS code-coverage category, fully
# covered, and NOTHING else -- zero functional bins measured.
_PURE_CODE_COVERAGE_ONLY = [
    {"name": "line", "percent": 100.0, "bins_total": 500, "bins_hit": 500},
]


def test_pre_fix_classifier_reproduces_the_documented_false_pass(tmp_path, monkeypatch):
    """Replay step: patch `classify_coverage_kind` back to the pre-fix
    shape the audit finding describes ("no code-enforced distinguishing
    rule" -- every category read as functional) and confirm the exact false
    PASS the audit found really does reappear on the real code path. This
    is what proves the guard in the next test is a genuine replay of a real
    incident, not an assumption that the fix matters."""
    root = tmp_path / "proj"
    root.mkdir()
    _insert_coverage(root, _PURE_CODE_COVERAGE_ONLY)

    monkeypatch.setattr(ca, "classify_coverage_kind", lambda name: ca.COVERAGE_KIND_FUNCTIONAL)

    report = fcs.analyze_functional_coverage_signoff(root)
    assert report["excluded_code_coverage_bins"] == []
    assert report["status"] == fcs.STATUS_SIGNOFF_READY
    # The real, reproduced false PASS the audit finding named:
    assert report["functional_coverage_signoff_ready"] is True


def test_real_fix_blocks_the_same_reproduced_scenario(tmp_path):
    """The permanent regression guard: on the IDENTICAL fixture, with the
    real (unpatched) `classify_coverage_kind`, this must never again reach
    `functional_coverage_signoff_ready == True` off a pure code-coverage
    category with zero functional bins measured."""
    root = tmp_path / "proj"
    root.mkdir()
    _insert_coverage(root, _PURE_CODE_COVERAGE_ONLY)

    report = fcs.analyze_functional_coverage_signoff(root)
    assert report["excluded_code_coverage_bins"] == ["line"]
    assert report["status"] != fcs.STATUS_SIGNOFF_READY
    assert report["functional_coverage_signoff_ready"] is not True
