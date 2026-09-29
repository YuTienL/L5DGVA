"""GET /api/evidence-integrity-signoff-blockers -- the Evidence Integrity +
Signoff Blocker Center dashboard card (item:
dashboard_evidence_integrity_signoff_blocker_ui, Web Control Plane theme,
CLAUDE_L5_WEB_CONTROL_PLANE_MASTER.md sections 342-402).

REUSE OVER REINVENT: `dv_harness/evidence_integrity_states.py` and
`dv_harness/signoff_blocker_list.py` already exist and already compute this
batch's own real per-project evidence-integrity rollup (VALID/STALE/
SUPERSEDED/CONTRADICTED/CORRUPT/UNKNOWN, over every recorded golden-scenario
capsule and signoff freeze) and the real twelve-dimension, worst-wins
signoff-blocker rollup (CLOSED/NOT_CLOSED/INCOMPLETE_EVIDENCE) -- this change
adds NO new analysis engine behind the card. It is a pure dashboard-wiring
gap, closed the same way the Generation Readiness Center card was: a thin
`_read_evidence_integrity_signoff_blocker_state()` reader following the
file's existing `{"available", "error"}` honest-empty-state contract, one
read-only GET endpoint, and a fetch-once + client-side-render card.

Unlike `design_knowledge_correlation.py`/`requirement_contract.py`/
`vplan_artifact.py` (deliberately generic engines needing a caller-populated
`.dv-harness/.../sources.json` convention), BOTH `evidence_integrity_states.py`
and `signoff_blocker_list.py` take a real project `root` directly and read
this project's own real `evidence.duckdb` / signoff freeze store / waiver
ledger / functional-coverage evidence themselves -- so this endpoint calls
both LIVE on every request, exactly like `/api/generation-readiness` calls
`derive_generation_readiness(root)` live.

These tests prove:
  * The card READS the real modules. The served `blocker_report` is compared
    against what `signoff_blocker_list.derive_signoff_blockers()` itself
    computes over the identical project state -- never a string typed into
    the test, so a dashboard-local re-derivation that drifted from the real
    analysis would fail here.
  * The Evidence Truth Rule holds on the served surface: a bare project with
    no evidence recorded at all must report an honest NOT_AVAILABLE/
    INCOMPLETE_EVIDENCE, never a fabricated VALID/CLOSED -- the negative
    control this project's house style requires -- and a genuinely corrupt
    `evidence.duckdb` must surface its own reason/detail rather than a bare
    500 or a silently empty card.

The real dashboard server is started for real on a free local port and
driven over real HTTP, reusing test_dashboard_interactive.py's own harness
helpers -- the same cross-test import convention
test_dashboard_requirement_vplan_center.py already uses.
"""
from __future__ import annotations

import shutil
import urllib.request
from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")

from dv_harness_tests.test_dashboard_interactive import (
    _free_port,
    _get,
    _mk_dashboard_project,
    _start_dashboard,
    _wait_ready,
)


def _strip_evaluated_at(obj):
    """Recursively drop every `evaluated_at` key -- waiver_store.status_report()'s
    own real wall-clock stamp, taken independently on each real call, so two
    real invocations of the same report can never be compared for byte
    equality without stripping it first."""
    if isinstance(obj, dict):
        return {k: _strip_evaluated_at(v) for k, v in obj.items() if k != "evaluated_at"}
    if isinstance(obj, list):
        return [_strip_evaluated_at(v) for v in obj]
    return obj


def _record_expired_waiver(root: Path, waiver_id: str = "W-1", item: str = "cov_a") -> None:
    """The identical real fixture recipe test_signoff_blocker_list.py's own
    suite already establishes -- a genuine section-237 waiver, expired, so
    waiver_store.derive_status() honestly reports it not VALID."""
    from dv_harness import waiver_store as ws

    ws.record_waiver(root, {
        "waiver_id": waiver_id, "item": item, "reason": "known limitation, accepted by design",
        "evidence": "see review notes", "approver": "alice",
        "affected_version": {"spec_revision": "r1"}, "risk": "LOW",
        "created_at": "2026-01-01T00:00:00+00:00",
        "expires_at": "2020-01-01T00:00:00+00:00",
        "scope": {
            "requirement_ids": ["REQ-1"], "subsystem": "usb3", "spec_revision": "r1",
            "design_evidence_hash": "abc123", "approval_id": "AP-1", "scope_hash": "hash1",
        },
    })


def test_evidence_integrity_signoff_blocker_honest_empty_state_on_a_bare_project():
    """A bare project has recorded no golden-scenario capsule, no signoff
    freeze, no waiver, and no functional-coverage evidence at all -- the
    served report must be the real, honest NOT_AVAILABLE/INCOMPLETE_EVIDENCE
    both real modules themselves report for that state, never a fabricated
    VALID/CLOSED. This is the required negative control."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _get(base, "/api/evidence-integrity-signoff-blockers")
        assert status == 200
        assert data["available"] is True
        assert data["error"] is None

        ir = data["integrity_report"]
        assert ir["status"] == "NOT_AVAILABLE"
        assert ir["capsule_count"] == 0
        assert ir["freeze_count"] == 0

        br = data["blocker_report"]
        assert br["signoff_status"] == "INCOMPLETE_EVIDENCE"
        # A project with nothing recorded must never be reported as having a
        # real blocker -- "nobody has evidence for this dimension yet" is a
        # different, honestly separate fact from "a blocker was found".
        assert br["signoff_blockers"] == []
        assert len(br["dimensions"]) == 12
    finally:
        shutil.rmtree(tmp)


def test_evidence_integrity_signoff_blocker_reports_the_real_reports_over_real_evidence():
    """A real, expired waiver recorded through the real waiver_store.py ledger
    writer must drive signoff_blocker_list.py's own real waiver_status
    dimension to UNMET and the whole rollup to NOT_CLOSED (worst-wins) -- and
    the served report must equal what derive_signoff_blockers() itself
    computes over the identical project state, proving the endpoint reads
    the real module rather than re-deriving anything."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        _record_expired_waiver(tmp)

        status, data = _get(base, "/api/evidence-integrity-signoff-blockers")
        assert status == 200
        assert data["available"] is True
        assert data["error"] is None

        from dv_harness import evidence_integrity_states as eis
        from dv_harness import signoff_blocker_list as sbl

        expected_integrity = eis.classify_project_evidence_integrity(tmp)
        assert data["integrity_report"] == expected_integrity

        expected_blockers = sbl.derive_signoff_blockers(
            tmp, evidence_integrity_report=expected_integrity)
        served_br = data["blocker_report"]
        # waiver_store.status_report()'s own real `evaluated_at` is a genuine
        # wall-clock stamp taken independently by the server's own request
        # and this test's own follow-up call -- strip it (and nothing else)
        # before comparing, the identical convention
        # test_dashboard_requirement_vplan_center.py's own suite already
        # uses for vplan_artifact.py's `generated_at`.
        assert _strip_evaluated_at(served_br) == _strip_evaluated_at(expected_blockers)

        assert served_br["signoff_status"] == "NOT_CLOSED"
        names = {b["dimension_name"] for b in served_br["signoff_blockers"]}
        assert "waiver_status" in names
        waiver_blocker = next(b for b in served_br["signoff_blockers"]
                               if b["dimension_name"] == "waiver_status")
        assert "W-1" in " ".join(waiver_blocker["reasons"])
    finally:
        shutil.rmtree(tmp)


def test_evidence_integrity_signoff_blocker_reports_a_corrupt_evidence_db_honestly():
    """A genuinely corrupt evidence.duckdb (an existing file that is not a
    real DuckDB database) must surface as this endpoint's own
    reason/detail -- never a bare 500, and never a silently empty card
    claiming nothing is wrong."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        from dv_harness.evidence_db import default_db_path
        p = default_db_path(tmp)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("not a real duckdb file", encoding="utf-8")

        status, data = _get(base, "/api/evidence-integrity-signoff-blockers")
        assert status == 200
        assert data["available"] is True
        assert data["error"]["reason"] == "EVIDENCE_INTEGRITY_CLASSIFICATION_FAILED"
        assert data["integrity_report"] is None
        assert data["blocker_report"] is None
    finally:
        shutil.rmtree(tmp)


def test_evidence_integrity_signoff_blocker_card_is_served_and_wired_into_the_page_load():
    """The card must exist in the served HTML and be refreshed by load() --
    an endpoint no page ever calls is exactly the PARTIALLY_WIRED shape this
    item exists to avoid, and this card must follow the same rendering
    convention (tiles + tables, fetch-once, no new template) as the
    Generation Readiness / Requirement-vPlan cards it was asked to reuse."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        with urllib.request.urlopen(base + "/", timeout=10) as resp:
            html = resp.read().decode("utf-8")
        assert 'id="evidenceIntegritySignoffBlockersCard"' in html
        assert "Evidence Integrity + Signoff Blocker Center" in html
        assert "'/api/evidence-integrity-signoff-blockers'" in html
        assert "await loadEvidenceIntegritySignoffBlockers();" in html
        assert 'id="eisTiles"' in html
        assert 'id="eisIntegrityBody"' in html
        assert 'id="eisDimensionsBody"' in html
        # This card is read-only, matching the convention every sibling card
        # it reuses follows -- no POST verb of its own.
        card_html = html.split('id="evidenceIntegritySignoffBlockersCard"')[1].split("</div>")[0]
        assert "Read-only" in card_html
    finally:
        shutil.rmtree(tmp)
