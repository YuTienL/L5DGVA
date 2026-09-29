"""GET /api/system-smoke-proof -- the Integration Proof Ladder dashboard card
(TARGETED_HARDENING item dashboard_integration_proof_ladder_ui, part of the
Web Control Plane theme).

The item asks for "a route + card surfacing system_build_proof.py's real
smoke-proof ladder (Build -> Elaborate -> Boot -> Shared-Resource ->
One-Subsystem -> Two-Subsystem -> End-to-End -> WAVE -> Scoreboard ->
SYSTEM_READY) rung-by-rung status for a project that has run it."

REUSE OVER REINVENT: dv_harness/system_build_proof.py already exists and
already computes the real, section-206-shaped ladder this card needs -- this
change adds NO new analysis anywhere. system_build_proof.run_system_smoke_
proof() needs real inputs a dashboard cannot gather on its own (composed
source sets, a system filelist, an fsdb path, an evidence-db job id), so this
card follows the exact convention subsystem_maturity_gate.py's and
generation_readiness.py's own real consumers of this ladder already use: it
reads an already-produced `system_build_proof.SmokeProofReport.to_dict()`
document a caller supplies, off this project's own conventional
`.dv-harness/system_build_proof/smoke_proof_report.json` -- the identical
fetch-real-artifact-and-render shape _read_generation_readiness_state() /
_read_design_knowledge_state() already established, reused rather than a new
rendering approach.

These tests exist to prove two things beyond "the endpoint returns 200":

  * The card serves the REAL SmokeProofReport.to_dict() shape verbatim --
    never a dashboard-local re-derivation of a rung's status.
  * The Evidence Truth Rule holds on the served surface: a bare project (no
    report ever run) must never render a fabricated ladder, and a malformed
    or structurally-foreign report file must surface its own honest reason
    rather than a bare 500 or a silently empty card.

The real dashboard server is started for real on a free local port and driven
over real HTTP, reusing test_dashboard_interactive.py's own harness helpers --
the same cross-test import convention test_dashboard_generation_readiness_
card.py already uses.
"""
from __future__ import annotations

import json
import shutil
import urllib.request
from pathlib import Path

from dv_harness_tests.test_dashboard_interactive import (
    _free_port,
    _get,
    _mk_dashboard_project,
    _start_dashboard,
    _wait_ready,
)


def _real_smoke_proof_report_dict(verdict: str = None) -> dict:
    """A real system_build_proof.SmokeProofReport.to_dict() document, built
    from the module's own real dataclasses (never a hand-typed JSON shape
    this test invents independently) -- every rung on the real ladder,
    PASSing, for the SYSTEM_READY case."""
    from dv_harness import system_build_proof as sbp

    verdict = verdict or sbp.SYSTEM_READY
    rungs = [sbp.RungResult(rung=r, status="PASS", reason=f"{r} passed against real evidence")
             for r in sbp.SMOKE_PROOF_LADDER]
    report = sbp.SmokeProofReport(
        verdict=verdict,
        evidence=f"every one of the {len(rungs)} smoke-proof rungs PASSED against real evidence",
        rungs=rungs,
    )
    return report.to_dict()


def _write_report(tmp: Path, payload, *, path: Path | None = None) -> Path:
    p = path or (tmp / ".dv-harness" / "system_build_proof" / "smoke_proof_report.json")
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, str):
        p.write_text(payload, encoding="utf-8")
    else:
        p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_smoke_proof_reports_honest_empty_state_on_a_bare_project():
    """A project that has never run the ladder must report {"available":
    False}, naming the real conventional path this endpoint looked for --
    never a fabricated ladder and never a silent empty-but-`available: True`
    response."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _get(base, "/api/system-smoke-proof")
        assert status == 200
        assert data["available"] is False
        assert data["report"] is None
        assert data["error"] is None
        assert data["report_path"].replace("\\", "/").endswith(
            ".dv-harness/system_build_proof/smoke_proof_report.json")
    finally:
        shutil.rmtree(tmp)


def test_smoke_proof_serves_the_real_report_verbatim_for_system_ready():
    """A real, on-disk SmokeProofReport.to_dict() (built from the module's
    own dataclasses) must be served byte-for-byte identical -- proving the
    endpoint reads the real artifact rather than re-deriving anything."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        from dv_harness import system_build_proof as sbp

        expected = _real_smoke_proof_report_dict()
        report_path = _write_report(tmp, expected)

        status, data = _get(base, "/api/system-smoke-proof")
        assert status == 200
        assert data["available"] is True
        assert data["error"] is None
        assert data["report"] == expected
        assert data["report"]["verdict"] == sbp.SYSTEM_READY
        assert len(data["report"]["rungs"]) == len(sbp.SMOKE_PROOF_LADDER)
        assert [r["rung"] for r in data["report"]["rungs"]] == list(sbp.SMOKE_PROOF_LADDER)
        assert data["report_path"].replace("\\", "/") == str(report_path).replace("\\", "/")
    finally:
        shutil.rmtree(tmp)


def test_smoke_proof_reports_a_halted_ladder_honestly():
    """A real FAIL-halted ladder (rungs after the failure are NOT_YET_RUN,
    a different fact from "checked and clean") must be served exactly as
    system_build_proof.py itself would report it -- never smoothed over."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        from dv_harness import system_build_proof as sbp

        rungs = []
        for i, r in enumerate(sbp.SMOKE_PROOF_LADDER):
            if i == 0:
                rungs.append(sbp.RungResult(rung=r, status="FAIL", reason="a real merge collision"))
            else:
                rungs.append(sbp.RungResult(rung=r, status="NOT_YET_RUN",
                                             reason=f"the ladder halted at {sbp.SMOKE_PROOF_LADDER[0]}"))
        report = sbp.SmokeProofReport(verdict=sbp.SMOKE_FAIL,
                                       evidence=f"smoke proof FAILED at {sbp.SMOKE_PROOF_LADDER[0]}",
                                       rungs=rungs)
        expected = report.to_dict()
        _write_report(tmp, expected)

        status, data = _get(base, "/api/system-smoke-proof")
        assert status == 200
        assert data["available"] is True
        assert data["report"]["verdict"] == sbp.SMOKE_FAIL
        assert data["report"]["triage_required"] is True
        assert data["report"]["rungs"][0]["status"] == "FAIL"
        assert data["report"]["rungs"][1]["status"] == "NOT_YET_RUN"
        assert data["report"] == expected
    finally:
        shutil.rmtree(tmp)


def test_smoke_proof_reports_malformed_json_honestly_never_a_500():
    """A file that exists but is not valid JSON must surface a named,
    honest error rather than a bare 500 or a silently empty card."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        _write_report(tmp, "{not valid json, at all")

        status, data = _get(base, "/api/system-smoke-proof")
        assert status == 200
        assert data["report"] is None
        assert data["error"]["reason"] == "MALFORMED_SMOKE_PROOF_REPORT_FILE"
    finally:
        shutil.rmtree(tmp)


def test_smoke_proof_reports_structurally_foreign_document_honestly():
    """A file that IS valid JSON but is not a SmokeProofReport.to_dict()
    document (missing 'verdict'/'rungs') must never be silently rendered as
    if it were a real ladder -- named and refused instead."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        _write_report(tmp, {"unrelated": "document", "no_ladder_here": True})

        status, data = _get(base, "/api/system-smoke-proof")
        assert status == 200
        assert data["report"] is None
        assert data["error"]["reason"] == "NOT_A_SMOKE_PROOF_REPORT"
    finally:
        shutil.rmtree(tmp)


def test_smoke_proof_reports_unrecognized_verdict_honestly():
    """A verdict outside system_build_proof.SMOKE_VERDICTS (SYSTEM_READY /
    SMOKE_FAIL / SMOKE_NOT_PROVEN) is never rendered as if it were a real,
    recognized ladder outcome -- this is the negative control proving the
    card refuses to fabricate meaning for a value it cannot honestly
    interpret."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        from dv_harness import system_build_proof as sbp

        _write_report(tmp, {"schema_version": "1.0", "ladder": [], "verdict": "TOTALLY_MADE_UP",
                             "evidence": "n/a", "triage_required": False, "authorizes": "nothing",
                             "rungs": [], "by_status": {}, "merge_report": None})

        status, data = _get(base, "/api/system-smoke-proof")
        assert status == 200
        assert data["report"] is None
        assert data["error"]["reason"] == "UNRECOGNIZED_SMOKE_PROOF_VERDICT"
        assert data["error"]["detail"]["verdict"] == "TOTALLY_MADE_UP"
        assert set(data["error"]["detail"]["known_verdicts"]) == set(sbp.SMOKE_VERDICTS)
    finally:
        shutil.rmtree(tmp)


def test_smoke_proof_report_query_param_overrides_the_conventional_path():
    """?report=<path> must read from the named file rather than the
    conventional one, the same override convention /api/design-knowledge's
    ?sources= already uses."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        alt_path = tmp / "elsewhere" / "my_report.json"
        expected = _real_smoke_proof_report_dict()
        _write_report(tmp, expected, path=alt_path)

        # The conventional path still has nothing -- proves the override is
        # really what is being read, not a coincidental fallback.
        status_default, data_default = _get(base, "/api/system-smoke-proof")
        assert data_default["available"] is False

        import urllib.parse
        status, data = _get(base, "/api/system-smoke-proof?report="
                             + urllib.parse.quote(str(alt_path)))
        assert status == 200
        assert data["available"] is True
        assert data["report"] == expected
        assert data["report_path"].replace("\\", "/") == str(alt_path).replace("\\", "/")
    finally:
        shutil.rmtree(tmp)


def test_smoke_proof_card_is_served_and_wired_into_the_page_load():
    """The card must exist in the served HTML and be refreshed by load() --
    an endpoint no page ever calls is exactly the PARTIALLY_WIRED shape this
    gap-close exists to avoid, and this card must follow the SAME rendering
    convention as the Generation Readiness card it was asked to reuse (tiles
    + a table, fetch-once, no new template)."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        with urllib.request.urlopen(base + "/", timeout=10) as resp:
            html = resp.read().decode("utf-8")
        assert 'id="smokeProofCard"' in html
        assert "Integration Proof Ladder" in html
        assert "'/api/system-smoke-proof" in html
        assert "await loadSmokeProof();" in html
        assert 'id="smokeProofTiles"' in html
        assert 'id="smokeProofTableBody"' in html
        for header in ("Rung", "Status", "Reason"):
            assert f">{header}<" in html
        # Read-only, matching every reader function this card reuses the
        # convention of -- no POST verb of its own.
        assert "Read-only" in html.split('id="smokeProofCard"')[1].split("</div>")[0]
    finally:
        shutil.rmtree(tmp)
