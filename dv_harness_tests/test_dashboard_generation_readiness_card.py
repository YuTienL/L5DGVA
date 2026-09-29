"""GET /api/generation-readiness -- the GUI Generation Center dashboard card
(spec section 214, SPEC_TO_SYSTEM_UVM_COMPLETE.md).

Section 214 asks for "a dashboard card surfacing generation_readiness.py's real
20-row Generation Readiness Matrix, reusing dashboard.py's existing
card-rendering conventions (see its Protocols/AMBA/Research cards) rather than
inventing a new rendering approach."

REUSE OVER REINVENT: dv_harness/generation_readiness.py already exists (built
2026-09-06, see its own module docstring and the matching CLAUDE.md section)
and already computes the real, section-211-shaped twenty-row matrix this card
needs -- this change adds NO new analysis anywhere. It is a pure dashboard
wiring gap, closed the same way dashboard.py's own "AMBA Fabric / VIP Bind /
Scoreboard" (GUI-09) and "Research / Capability Evolution" (GUI-10) cards
were: a thin `_read_generation_readiness_state()` reader with the file's
existing `{"available", "error"}` honest-empty-state contract, one read-only
GET endpoint, and a fetch-once + client-side-render card following the exact
same shape those two cards already use.

These tests exist to prove two things beyond "the endpoint returns 200":

  * The card READS the real module. Every asserted value is compared against
    what generation_readiness.derive_generation_readiness() itself computes
    over the identical project root -- never against a string typed into the
    test, so a dashboard-local re-derivation that drifted from the real
    matrix would fail here.
  * The Evidence Truth Rule holds on the served surface, not only inside the
    underlying module: a bare project (nothing generated, nothing registered)
    must never render a fabricated READY row, and a real failure inside the
    underlying module must surface its own reason/detail rather than a bare
    500 or a silently empty card.

The real dashboard server is started for real on a free local port and driven
over real HTTP, reusing test_dashboard_interactive.py's own harness helpers --
the same cross-test import convention test_dashboard_amba_card.py and
test_dashboard_research_card.py already use.
"""
from __future__ import annotations

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


def _matrix_without_timestamp(matrix: dict) -> dict:
    """generated_at is a real wall-clock stamp (second precision) -- strip it
    before comparing two independently-computed matrices so a test never
    flakes on a run that straddles a second boundary. Every other field must
    still match exactly."""
    out = dict(matrix)
    out.pop("generated_at", None)
    return out


def test_generation_readiness_reports_the_real_full_matrix_over_a_bare_project():
    """A project with nothing generated and nothing registered still gets all
    twenty section-211 rows back (they are mandatory, never omitted for being
    UNKNOWN), and the served matrix is byte-identical to calling
    derive_generation_readiness() directly over the same root -- proving the
    endpoint reads the real module rather than re-deriving anything."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        from dv_harness.generation_readiness import ROWS, derive_generation_readiness

        status, data = _get(base, "/api/generation-readiness")
        assert status == 200
        assert data["available"] is True
        assert data["error"] is None
        matrix = data["matrix"]
        assert matrix is not None

        assert len(matrix["rows"]) == len(ROWS) == 20
        assert [r["row_id"] for r in matrix["rows"]] == [r.row_id for r in ROWS]

        expected = derive_generation_readiness(tmp, deep=True)
        assert _matrix_without_timestamp(matrix) == _matrix_without_timestamp(expected)

        # Evidence Truth Rule, on the served surface: a bare project supplies
        # no generation artifact at all, so no row may fabricate a READY
        # verdict that project evidence never actually backed.
        for row in matrix["rows"]:
            if row["status"] == "READY":
                assert row["project_evidence_status"] == "READY", row
    finally:
        shutil.rmtree(tmp)


def test_generation_readiness_deep_query_param_mirrors_the_cli_no_deep_flag():
    """?deep=0 must reach derive_generation_readiness(..., deep=False) --
    skipping the SYS-1..SYS-30 cross-subsystem chain -- exactly like the CLI's
    own `--no-deep` flag, and the served matrix must equal that direct call."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        from dv_harness.generation_readiness import derive_generation_readiness

        status, data = _get(base, "/api/generation-readiness?deep=0")
        assert status == 200
        assert data["available"] is True
        assert data["matrix"]["deep_analysis"] is False

        expected = derive_generation_readiness(tmp, deep=False)
        assert _matrix_without_timestamp(data["matrix"]) == _matrix_without_timestamp(expected)

        # The default (no query param, and an explicit deep=1) still runs the
        # deep chain.
        status, data_default = _get(base, "/api/generation-readiness")
        assert data_default["matrix"]["deep_analysis"] is True
        status, data_explicit = _get(base, "/api/generation-readiness?deep=1")
        assert data_explicit["matrix"]["deep_analysis"] is True
    finally:
        shutil.rmtree(tmp)


def test_generation_readiness_reports_the_real_module_error_rather_than_a_500():
    """A GenerationReadinessError raised by the underlying module (a row's
    declared fact_source no longer resolving) must surface as this endpoint's
    own error reason/detail -- the same honest-error contract
    _read_amba_registry_state() already holds to -- never a bare 500 and
    never a silently empty/fabricated card."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        from dv_harness.generation_readiness import GenerationReadinessError

        def _raise(*args, **kwargs):
            raise GenerationReadinessError(
                "FACT_SOURCE_MODULE_UNIMPORTABLE",
                {"fact_source": "dv_harness.nonexistent_module.nope"})

        import dv_harness.generation_readiness as gr
        saved = gr.derive_generation_readiness
        gr.derive_generation_readiness = _raise
        try:
            status, data = _get(base, "/api/generation-readiness")
            assert status == 200
            assert data["available"] is False
            assert data["matrix"] is None
            assert data["error"]["reason"] == "FACT_SOURCE_MODULE_UNIMPORTABLE"
            assert data["error"]["detail"]["fact_source"] == \
                "dv_harness.nonexistent_module.nope"
        finally:
            gr.derive_generation_readiness = saved
    finally:
        shutil.rmtree(tmp)


def test_generation_readiness_card_is_served_and_wired_into_the_page_load():
    """The card must exist in the served HTML and be refreshed by load() -- an
    endpoint no page ever calls is exactly the PARTIALLY_WIRED shape this
    gap-close exists to avoid, and this card must follow the SAME rendering
    convention as the Protocols/AMBA/Research cards it was asked to reuse
    (tiles + a table, fetch-once, no new template)."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        with urllib.request.urlopen(base + "/", timeout=10) as resp:
            html = resp.read().decode("utf-8")
        assert 'id="generationReadinessCard"' in html
        assert "Generation Readiness Center" in html
        assert "'/api/generation-readiness" in html
        assert "await loadGenerationReadiness();" in html
        assert 'id="generationReadinessTiles"' in html
        assert 'id="generationReadinessTableBody"' in html
        # Reuses the shared table renderer's column header text, transcribed
        # verbatim from section 211's own seven columns -- never a renamed
        # or reordered set of headers.
        for header in ("Capability", "Status", "Existing Reuse", "Evidence",
                        "Gap", "Priority", "Action"):
            assert f">{header}<" in html
        # This card is read-only, matching every reader function it reuses
        # the convention of -- no POST verb of its own.
        assert "Read-only" in html.split('id="generationReadinessCard"')[1].split("</div>")[0]
    finally:
        shutil.rmtree(tmp)
