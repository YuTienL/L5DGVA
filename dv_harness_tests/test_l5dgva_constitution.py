"""Real tests for dv_harness/constitution_gate.py -- the Article 0
anti-drift enforcement (see docs/architecture/L5DGVA_CONSTITUTION.md and
CLAUDE.md's own Article 0 section).

No mocking: every test reads the real files on disk in this checkout.
"""
from pathlib import Path

import pytest

from dv_harness import constitution_gate as cg


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_constitution_document_exists_at_the_canonical_path():
    doc = _repo_root() / cg.CONSTITUTION_DOC_PATH
    assert doc.is_file()


def test_constitution_document_contains_article_0_and_all_five_dimensions():
    text = (_repo_root() / cg.CONSTITUTION_DOC_PATH).read_text(encoding="utf-8")
    assert "Article 0" in text
    for dim in cg.CONSTITUTIONAL_DIMENSIONS:
        assert dim in text, "missing constitutional dimension: %s" % dim


def test_constitution_document_contains_the_anti_drift_rule():
    text = (_repo_root() / cg.CONSTITUTION_DOC_PATH).read_text(encoding="utf-8")
    assert "ARCHITECTURE_CONFLICT" in text
    assert "Anti-Drift Rule" in text


def test_claude_md_carries_the_article_0_pointer():
    text = (_repo_root() / "CLAUDE.md").read_text(encoding="utf-8")
    assert "Article 0" in text
    assert cg.CONSTITUTION_DOC_PATH in text


def test_claude_md_article_0_section_precedes_core_operating_rules():
    """Article 0 must sit above ordinary rules -- checked by real
    position, not just presence."""
    text = (_repo_root() / "CLAUDE.md").read_text(encoding="utf-8")
    article_0_pos = text.index("Article 0")
    core_rules_pos = text.index("Core Operating Rules")
    assert article_0_pos < core_rules_pos


def test_check_constitution_intact_passes_on_the_real_repo():
    result = cg.check_constitution_intact(_repo_root())
    assert result.status == "PASS", result.reasons


def test_check_constitution_intact_fails_when_constitution_doc_is_missing(tmp_path):
    (tmp_path / "CLAUDE.md").write_text(
        "# X\n## Article 0\nsee docs/architecture/L5DGVA_CONSTITUTION.md\n",
        encoding="utf-8",
    )
    result = cg.check_constitution_intact(tmp_path)
    assert result.status == "FAIL"
    assert any("constitution" in r.lower() for r in result.reasons)


def test_check_constitution_intact_fails_when_claude_md_pointer_is_missing(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("# X\nno pointer here\n", encoding="utf-8")
    doc_dir = tmp_path / "docs" / "architecture"
    doc_dir.mkdir(parents=True)
    (doc_dir / "L5DGVA_CONSTITUTION.md").write_text(
        "# Constitution\n## Article 0\n" + "\n".join(cg.CONSTITUTIONAL_DIMENSIONS)
        + "\nAnti-Drift Rule ARCHITECTURE_CONFLICT\n",
        encoding="utf-8",
    )
    result = cg.check_constitution_intact(tmp_path)
    assert result.status == "FAIL"
    assert any("claude.md" in r.lower() or "pointer" in r.lower() for r in result.reasons)


def test_check_constitution_intact_fails_when_a_dimension_is_silently_removed(tmp_path):
    doc_dir = tmp_path / "docs" / "architecture"
    doc_dir.mkdir(parents=True)
    # Drop one of the five dimensions -- simulates a future silent weakening.
    remaining = [d for d in cg.CONSTITUTIONAL_DIMENSIONS if d != "EVIDENCE_GROUNDED"]
    (doc_dir / "L5DGVA_CONSTITUTION.md").write_text(
        "# Constitution\n## Article 0\n" + "\n".join(remaining)
        + "\nAnti-Drift Rule ARCHITECTURE_CONFLICT\n",
        encoding="utf-8",
    )
    (tmp_path / "CLAUDE.md").write_text(
        "# X\n## Article 0\nsee docs/architecture/L5DGVA_CONSTITUTION.md\n## Core Operating Rules\n",
        encoding="utf-8",
    )
    result = cg.check_constitution_intact(tmp_path)
    assert result.status == "FAIL"
    assert any("EVIDENCE_GROUNDED" in r for r in result.reasons)


def test_final_constitutional_compliance_is_not_yet_pass_status_is_a_distinct_value():
    """L5DGVA_CONSTITUTIONAL_COMPLIANCE is a final-product-only gate --
    intact Article 0 text alone must not be conflated with full
    compliance (which additionally requires both continuous-learning
    loops OPERATIONAL, per the constitution document itself)."""
    assert cg.FINAL_COMPLIANCE_STATUS_INTERMEDIATE != "PASS"
