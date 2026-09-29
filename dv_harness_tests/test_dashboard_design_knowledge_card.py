"""GET /api/design-knowledge -- the Design Knowledge Explorer dashboard card
(CLAUDE_L5_WEB_CONTROL_PLANE_MASTER.md, section 342-402 theme; batch item
dashboard_design_knowledge_explorer).

`dv_harness/design_knowledge_correlation.py` already exists (see its own
module docstring and the matching CLAUDE.md section) and already computes a
real cross-source Design Knowledge Graph -- sources/facts/provenance plus
CONFLICT / GAP / DOCUMENTED_VS_IMPLEMENTED findings -- from a caller-supplied
`sources` list. That module is deliberately generic: it imports nothing from
`dv_harness` and discovers no project fact itself. Nothing in `dashboard.py`
ever surfaced it before this change -- REUSE OVER REINVENT: this card adds
NO new correlation logic anywhere. It is a pure dashboard wiring gap, closed
the same way the Generation Readiness / AMBA / Research cards were: a thin
`_read_design_knowledge_state()` reader with the file's existing
`{"available", "error"}` honest-empty-state contract, one read-only GET
endpoint, and a fetch-once + client-side-render card following the exact
same shape those cards already use.

These tests prove two things beyond "the endpoint returns 200":

  * The card READS the real module. The served report is compared against
    calling `design_knowledge_correlation.correlate()` directly over the
    identical `sources`/`expected_facts` -- never against a value typed into
    the test -- so a dashboard-local re-derivation of a conflict/gap/
    doc-vs-impl finding would fail here.
  * The Evidence Truth Rule holds on the served surface: a project with no
    `sources.json` on disk yet must never render a fabricated graph, and a
    malformed input file or a real `DesignKnowledgeCorrelationError` must
    surface its own reason/detail rather than a bare 500 or a silently
    empty card.

The real dashboard server is started for real on a free local port and
driven over real HTTP, reusing test_dashboard_interactive.py's own harness
helpers -- the same cross-test import convention
test_dashboard_generation_readiness_card.py already uses.
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


_SOURCES = [
    {
        "source_id": "spec_v1",
        "source_kind": "spec",
        "role": "SPEC_DECLARATION",
        "facts": [
            {"fact_key": "usb_wake_irq.active_level", "fact_type": "interrupt",
             "value": "HIGH", "evidence_ref": "spec.md:120"},
            {"fact_key": "feature_x.supported", "fact_type": "feature",
             "value": True, "evidence_ref": "spec.md:200"},
        ],
    },
    {
        "source_id": "rtl_extract",
        "source_kind": "rtl",
        "role": "IMPLEMENTATION_EVIDENCE",
        "facts": [
            {"fact_key": "usb_wake_irq.active_level", "fact_type": "interrupt",
             "value": "LOW", "evidence_ref": "top.v:44"},
        ],
    },
]

_EXPECTED_FACTS = [
    {"fact_key": "dma_engine.present", "reason": "required by architecture",
     "required_by": "arch_doc.md#5"},
]


def _write_design_knowledge_inputs(tmp: Path, sources=_SOURCES, expected=_EXPECTED_FACTS) -> None:
    d = tmp / ".dv-harness" / "design_knowledge"
    d.mkdir(parents=True, exist_ok=True)
    (d / "sources.json").write_text(json.dumps(sources), encoding="utf-8")
    if expected is not None:
        (d / "expected_facts.json").write_text(json.dumps(expected), encoding="utf-8")


def test_bare_project_reports_the_honest_empty_state_never_a_fabricated_graph():
    """No sources.json on disk yet -> available: False, naming the real
    conventional path this endpoint looked for -- never a fabricated report."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _get(base, "/api/design-knowledge")
        assert status == 200
        assert data["available"] is False
        assert data["report"] is None
        assert data["error"] is None
        assert data["sources_path"].endswith(
            str(Path(".dv-harness") / "design_knowledge" / "sources.json"))
    finally:
        shutil.rmtree(tmp)


def test_design_knowledge_reports_the_real_correlation_report():
    """A real sources.json (+ expected_facts.json) on disk must produce a
    report byte-identical to calling design_knowledge_correlation.correlate()
    directly over the identical inputs -- proving the endpoint reads/calls
    the real module rather than re-deriving anything -- and that report must
    genuinely contain one CONFLICT, one GAP, and one
    DOCUMENTED_VS_IMPLEMENTED_SPEC_ONLY finding (this fixture's own real,
    checked shape)."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        _write_design_knowledge_inputs(tmp)
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        from dv_harness.design_knowledge_correlation import correlate

        status, data = _get(base, "/api/design-knowledge")
        assert status == 200
        assert data["available"] is True
        assert data["error"] is None
        report = data["report"]
        assert report is not None

        expected = correlate(_SOURCES, _EXPECTED_FACTS)
        assert report == expected

        assert report["summary"]["conflict_count"] == 1
        assert report["summary"]["gap_count"] == 1
        assert report["summary"]["documented_vs_implemented_count"] == 1
        assert [c["fact_key"] for c in report["conflicts"]] == ["usb_wake_irq.active_level"]
        assert [g["fact_key"] for g in report["gaps"]] == ["dma_engine.present"]
        assert [d["finding_type"] for d in report["documented_vs_implemented"]] == \
            ["DOCUMENTED_VS_IMPLEMENTED_SPEC_ONLY"]

        # The Design Knowledge Graph's own SOURCE/FACT nodes must be present
        # and browsable, each fact node carrying real per-source provenance.
        graph = report["knowledge_graph"]
        source_ids = {s["source_id"] for s in graph["nodes"]["sources"]}
        assert source_ids == {"spec_v1", "rtl_extract"}
        fact_keys = {f["fact_key"] for f in graph["nodes"]["facts"]}
        assert {"usb_wake_irq.active_level", "feature_x.supported"} <= fact_keys
        conflicted = next(f for f in graph["nodes"]["facts"]
                           if f["fact_key"] == "usb_wake_irq.active_level")
        assert conflicted["consensus"] == "CONFLICT"
        assert {p["source_id"] for p in conflicted["provenance"]} == {"spec_v1", "rtl_extract"}
    finally:
        shutil.rmtree(tmp)


def test_malformed_sources_file_reports_the_real_reason_never_a_bare_500():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        d = tmp / ".dv-harness" / "design_knowledge"
        d.mkdir(parents=True, exist_ok=True)
        (d / "sources.json").write_text("{not valid json", encoding="utf-8")
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _get(base, "/api/design-knowledge")
        assert status == 200
        assert data["available"] is True
        assert data["report"] is None
        assert data["error"]["reason"] == "MALFORMED_SOURCES_FILE"
    finally:
        shutil.rmtree(tmp)


def test_sources_shape_rejected_by_correlate_reports_the_real_module_error():
    """A sources.json that parses as JSON but is not a shape correlate()
    itself accepts (DesignKnowledgeCorrelationError) must surface that
    module's own real error text, not a fabricated report."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        d = tmp / ".dv-harness" / "design_knowledge"
        d.mkdir(parents=True, exist_ok=True)
        (d / "sources.json").write_text(json.dumps({"not": "a list"}), encoding="utf-8")
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _get(base, "/api/design-knowledge")
        assert status == 200
        assert data["available"] is True
        assert data["report"] is None
        assert data["error"]["reason"] == "DESIGN_KNOWLEDGE_CORRELATION_INVALID_INPUT"
        assert "sources" in data["error"]["detail"]["message"]
    finally:
        shutil.rmtree(tmp)


def test_design_knowledge_card_is_served_and_wired_into_the_page_load():
    """The card must exist in the served HTML and be refreshed by load() --
    an endpoint no page ever calls is exactly the PARTIALLY_WIRED shape this
    gap-close exists to avoid."""
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        with urllib.request.urlopen(base + "/", timeout=10) as resp:
            html = resp.read().decode("utf-8")
        assert 'id="designKnowledgeCard"' in html
        assert "Design Knowledge Explorer" in html
        assert "'/api/design-knowledge" in html
        assert "await loadDesignKnowledge();" in html
        assert 'id="designKnowledgeTiles"' in html
        assert 'id="designKnowledgeSourcesBody"' in html
        assert 'id="designKnowledgeFactsBody"' in html
        assert 'id="designKnowledgeFindingsBody"' in html
        for header in ("Source ID", "Kind", "Role", "Fact Count",
                        "Fact Key", "Type(s)", "Consensus", "Distinct Values",
                        "Assertions", "Type", "Reason"):
            assert f">{header}<" in html
        # Read-only, matching every reader function this card reuses the
        # convention of -- no POST verb of its own.
        assert "Read-only" in html.split('id="designKnowledgeCard"')[1].split("</div>")[0]
    finally:
        shutil.rmtree(tmp)
