"""Real tests for dv_harness/governance_registry.py -- TASK_SCOPED_GOVERNANCE_RETRIEVAL
(see .work/phase3-dual-repo-consolidation/M4_5_GOVERNANCE_CONTEXT_ARCHITECTURE.md).

No mocking: reads the real registry JSON and the real files on disk in
this checkout.
"""
from pathlib import Path

import pytest

from dv_harness import governance_registry as gr


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_registry_file_exists_and_parses():
    entries = gr.load_registry(_repo_root())
    assert len(entries) > 0


def test_every_entry_has_a_valid_load_policy():
    entries = gr.load_registry(_repo_root())
    for e in entries:
        assert e["load_policy"] in gr.LOAD_POLICIES, e


def test_every_entry_summary_or_full_spec_path_exists_on_disk():
    """Reachability check: a registry entry that points nowhere real is
    worse than no registry at all -- this is the same discipline
    context_budget.py's own resident-pack check already applies."""
    root = _repo_root()
    entries = gr.load_registry(root)
    for e in entries:
        for key in ("summary_path", "full_spec_path"):
            p = e.get(key)
            if p:
                assert (root / p).exists(), "%s: %s does not exist (%s)" % (e["id"], p, key)


def test_claude_md_is_registered_as_always_on():
    entries = gr.load_registry(_repo_root())
    claude_md = [e for e in entries if e["id"] == "CLAUDE_MD"]
    assert len(claude_md) == 1
    assert claude_md[0]["load_policy"] == "ALWAYS_ON"


def test_l5dgva_governing_contract_corpus_is_evidence_on_demand_source_only():
    """The 25-document Parent-only corpus must never be an ALWAYS_ON or
    TASK_SCOPED item -- it is real, substantial (4.0MB/106,132 lines) and
    explicitly SOURCE_EVIDENCE_ONLY per the M4.5 governance-context
    requirement: never appended to CLAUDE.md, never loaded wholesale."""
    entries = gr.load_registry(_repo_root())
    corpus = [e for e in entries if e["id"] == "L5DGVA_GOVERNING_CONTRACT_CORPUS"]
    assert len(corpus) == 1
    assert corpus[0]["load_policy"] == "EVIDENCE_ON_DEMAND"
    assert corpus[0]["token_class"] == "SOURCE_EVIDENCE_ONLY"


def test_constitution_document_is_registered():
    entries = gr.load_registry(_repo_root())
    matches = [e for e in entries if e["id"] == "L5DGVA_CONSTITUTION"]
    assert len(matches) == 1


def test_get_entries_by_policy_filters_correctly():
    entries = gr.load_registry(_repo_root())
    always_on = gr.get_entries_by_policy(entries, "ALWAYS_ON")
    assert all(e["load_policy"] == "ALWAYS_ON" for e in always_on)
    assert len(always_on) >= 1


def test_no_duplicate_ids():
    entries = gr.load_registry(_repo_root())
    ids = [e["id"] for e in entries]
    assert len(ids) == len(set(ids)), "duplicate registry ids found"


def test_check_reachability_reports_zero_broken_paths_on_the_real_repo():
    result = gr.check_reachability(_repo_root())
    assert result.broken == [], result.broken


def test_check_reachability_catches_a_fabricated_broken_path(tmp_path):
    import json
    registry_dir = tmp_path / "dv_harness"
    registry_dir.mkdir()
    (registry_dir / "governance_registry.json").write_text(json.dumps({
        "schema_version": "1.0",
        "entries": [
            {"id": "FAKE", "load_policy": "EVIDENCE_ON_DEMAND", "token_class": "TEST",
             "trigger": "test", "priority": "LOW", "summary_path": "does/not/exist.md"},
        ],
    }), encoding="utf-8")
    result = gr.check_reachability(tmp_path)
    assert len(result.broken) == 1
