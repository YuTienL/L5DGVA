"""Phase 18 -- the knowledge-dedup gate on the AUTOMATIC vault write path.

`dv_harness/memory_dedup.py` and its 11 tests (test_memory_dedup.py) proved
the fingerprint/classification MECHANISM. They never touched the write path,
and a 2026-09-04 audit found the gate had exactly one caller: the manual
`dv-harness memory add` verb. `memory_router._maybe_write_vault_note()` --
the automatic write-through every real ENGINEERING_MEMORY/
ORGANIZATIONAL_MEMORY promotion goes through, and the only path that has
ever populated this project's own vault -- decided create-vs-update from
note-id identity alone, so a second record with a new memory_id but the same
root cause minted a second note. That is the spec's own
`USB3_LFPS_issue1/issue2/issue3` scenario, reachable in production.

Every test here drives the REAL `route_and_store()` against a REAL vault on
disk and asserts what is actually on the filesystem afterwards -- never that
the classifier merely returned a string.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from dv_harness import memory_dedup, memory_vault as mv
from dv_harness.memory import MemoryRetriever, MemoryStore
from dv_harness.memory_router import _classify_vault_candidate, route_and_store


@pytest.fixture()
def project():
    root = Path(tempfile.mkdtemp(prefix="dv-dedup-writepath-"))
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _cfg(root: Path) -> dict:
    return {
        "knowledge_center": {"enabled": False},
        "memory": {"vault_path": str(root / "vault"), "obsidian_cli": "disabled", "git_enabled": False},
    }


def _engineering_record(**over) -> dict:
    """A record that really clears engineering_admission_gate() (verified +
    real evidence + HIGH confidence + a reusable claim), so these tests
    exercise the promotion write-through rather than a Working-tier demotion."""
    record = {
        "kind": "root_cause", "verified": True, "protocol": "USB3",
        "scope": "link_training",
        "title": "LFPS polling handshake stalls at U1 exit",
        "root_cause": "missing prefetch guard on the lfps detect synchronizer",
        "fix": "add a two-flop synchronizer before lfps_detect",
        "symptoms": ["lfps polling timeout", "u1 exit stall"],
        "confidence": "HIGH",
        "evidence": ["sim.log:8821 UVM_ERROR lfps polling timeout",
                     "rtl/usb3_link.sv:412 unsynchronized lfps_detect"],
    }
    record.update(over)
    return record


def _engineering_notes(root: Path) -> list:
    d = root / "vault" / "06_Agent_Memory" / "Engineering"
    return sorted(d.glob("*.md")) if d.exists() else []


def _related_knowledge(path: Path) -> str:
    _, body = mv.parse_note_markdown(path.read_text(encoding="utf-8"))
    return mv._body_to_sections(body).get("Related Knowledge", "")


# ---------------------------------------------------------------------------
# DUPLICATE: a second record for the same knowledge folds, never mints
# ---------------------------------------------------------------------------

def test_a_duplicate_promotion_folds_into_the_note_already_on_file(project):
    cfg = _cfg(project)
    first = route_and_store(project, _engineering_record(), cfg=cfg)
    assert first["destination"] == "ENGINEERING_MEMORY"
    assert first["vault_write"]["ok"] is True
    assert first["vault_write"]["dedup_classification"] == "NEW"
    assert first["vault_write"]["note_created"] is True

    # Same 5 fingerprint fields, reworded so it is a genuinely NEW record to
    # the JSON store (find_confirming_engineering_match() keys on an EXACT
    # root_cause string, so this does not confirm the first record -- it is a
    # real second memory_id, which is exactly the case the old note-id-only
    # check could not see).
    second = route_and_store(project, _engineering_record(
        root_cause="on the lfps detect synchronizer a missing prefetch guard"), cfg=cfg)
    assert second["memory_id"] != first["memory_id"]
    assert second.get("confirmed_existing") is not True

    vault = second["vault_write"]
    assert vault["dedup_classification"] == "DUPLICATE"
    assert vault["note_created"] is False
    assert vault["folded_into"] == first["memory_id"]

    notes = _engineering_notes(project)
    assert len(notes) == 1, "a duplicate root cause must never mint a second note"
    assert notes[0].stem == first["memory_id"]
    # Traceability: the absorbing note names the durable record it absorbed.
    assert second["memory_id"] in _related_knowledge(notes[0])
    # The JSON record itself is still written -- the fold is a vault-mirror
    # decision, never a reason to lose the system of record.
    assert MemoryStore(project).get(second["memory_id"]) is not None


def test_folding_the_same_record_twice_appends_only_one_recurrence_line(project):
    cfg = _cfg(project)
    first = route_and_store(project, _engineering_record(), cfg=cfg)
    dup = _engineering_record(root_cause="on the lfps detect synchronizer a missing prefetch guard")
    second = route_and_store(project, dup, cfg=cfg)
    third = route_and_store(project, {**dup, "memory_id": second["memory_id"]}, cfg=cfg)

    assert third["vault_write"]["already_folded"] is True
    note = _engineering_notes(project)[0]
    assert note.stem == first["memory_id"]
    assert _related_knowledge(note).count(second["memory_id"]) == 1


# ---------------------------------------------------------------------------
# UPDATE_EXISTING: the existing note is EXTENDED, and the new circumstances
# (which are the new knowledge) survive the fold
# ---------------------------------------------------------------------------

def test_update_existing_extends_the_note_with_the_new_circumstances(project):
    cfg = _cfg(project)
    first = route_and_store(project, _engineering_record(), cfg=cfg)
    second = route_and_store(project, _engineering_record(
        root_cause="missing prefetch guard on the lfps detect synchronizer of the device",
        title="warm reset replay wedges the link",
        scope="warm_reset_replay",
        symptoms=["link stuck in recovery after warm reset"],
    ), cfg=cfg)

    vault = second["vault_write"]
    assert vault["dedup_classification"] == "UPDATE_EXISTING"
    assert vault["note_created"] is False
    assert vault["folded_into"] == first["memory_id"]

    notes = _engineering_notes(project)
    assert len(notes) == 1
    related = _related_knowledge(notes[0])
    assert second["memory_id"] in related
    assert "configuration: warm_reset_replay" in related
    assert "link stuck in recovery after warm reset" in related


def test_a_fold_never_overwrites_the_absorbing_notes_own_content(project):
    """APPEND-ONLY: the fold writes into `Related Knowledge` and nothing else,
    so the root cause/fix already on the note survive verbatim."""
    cfg = _cfg(project)
    first = route_and_store(project, _engineering_record(), cfg=cfg)
    note = _engineering_notes(project)[0]
    before = mv._body_to_sections(mv.parse_note_markdown(note.read_text(encoding="utf-8"))[1])

    route_and_store(project, _engineering_record(
        root_cause="on the lfps detect synchronizer a missing prefetch guard"), cfg=cfg)

    after = mv._body_to_sections(mv.parse_note_markdown(note.read_text(encoding="utf-8"))[1])
    assert after["Root Cause"] == before["Root Cause"]
    assert after["Fix"] == before["Fix"]
    assert after["Evidence"] == before["Evidence"]
    assert after["Related Knowledge"] != before["Related Knowledge"]
    assert first["memory_id"] == note.stem


# ---------------------------------------------------------------------------
# NEW / RELATED: genuinely different knowledge still gets its own note
# ---------------------------------------------------------------------------

def test_a_different_protocol_is_never_folded_and_gets_its_own_note(project):
    """memory_dedup's protocol hard gate, now proven through the real write
    path: a PCIe record is not a duplicate of a USB3 one however similar the
    wording is."""
    cfg = _cfg(project)
    route_and_store(project, _engineering_record(), cfg=cfg)
    other = route_and_store(project, _engineering_record(protocol="PCIe"), cfg=cfg)

    assert other["vault_write"]["dedup_classification"] == "NEW"
    assert other["vault_write"]["note_created"] is True
    assert len(_engineering_notes(project)) == 2


def test_a_related_candidate_creates_its_own_note_and_wikilinks_the_overlap(project):
    cfg = _cfg(project)
    first = route_and_store(project, _engineering_record(), cfg=cfg)
    second = route_and_store(project, _engineering_record(
        root_cause="missing prefetch guard causes a scrambler seed mismatch on lane reversal"),
        cfg=cfg)

    assert second["vault_write"]["dedup_classification"] == "RELATED"
    assert second["vault_write"]["note_created"] is True
    assert len(_engineering_notes(project)) == 2

    new_note = project / "vault" / second["vault_write"]["path"]
    assert f"[[{first['memory_id']}]]" in _related_knowledge(new_note)
    # The link is real to the vault's own traversal, not just to a reader.
    provider = mv.get_active_provider(project, cfg)
    hits = provider.search({"linked_to": first["memory_id"]}, limit=10)
    assert [r["note_id"] for r in hits["results"]] == [second["memory_id"]]


# ---------------------------------------------------------------------------
# Scope of the gate: which writes it may and may not touch
# ---------------------------------------------------------------------------

def test_the_gate_never_fires_for_job_or_project_memory(project):
    """Job/Project notes are per-run/per-project by design (see
    memory_dedup.DEDUP_SCOPE_MEMORY_LEVELS). Two identical job records are two
    real jobs, not one duplicated piece of reusable knowledge."""
    cfg = _cfg(project)
    for job_id in (7, 8):
        result = route_and_store(project, {
            "kind": "job_failure", "job_id": job_id, "pattern": "usb_ep0_timeout",
            "protocol": "USB3", "title": "LSF job reached EXIT",
        }, cfg=cfg)
        assert result["destination"] == "JOB_MEMORY"
        assert "dedup_classification" not in result["vault_write"]

    job_notes = list((project / "vault" / "06_Agent_Memory" / "Job").glob("*.md"))
    assert len(job_notes) == 2


def test_an_organizational_candidate_is_not_folded_into_its_own_engineering_note(project):
    """An Engineering -> Organizational promotion writes the same knowledge a
    second time BY DESIGN. Compared across tiers it is a textbook DUPLICATE of
    its own engineering note, so a tier-blind gate would make the
    Organizational tier unwritable. The corpus is restricted to the
    candidate's own tier for exactly that reason."""
    cfg = _cfg(project)
    stored = route_and_store(project, _engineering_record(), cfg=cfg)
    note = _engineering_notes(project)[0]
    fm, body = mv.parse_note_markdown(note.read_text(encoding="utf-8"))
    sections = mv._body_to_sections(body)

    same_tier = _classify_vault_candidate(project, cfg, "ENGINEERING_MEMORY",
                                           {**fm, "id": "MEM-DIFFERENT01"}, sections)
    assert same_tier["classification"] == "DUPLICATE"
    assert same_tier["best_match"]["note_id"] == stored["memory_id"]

    promoted = _classify_vault_candidate(project, cfg, "ORGANIZATIONAL_MEMORY",
                                          {**fm, "id": "MEM-DIFFERENT01",
                                           "memory_level": "organizational"}, sections)
    assert promoted["classification"] == "NEW"
    assert promoted["candidate_count_compared"] == 0


def test_a_re_write_of_the_same_memory_id_still_updates_its_own_note(project):
    """Regression guard on the gate's placement: it runs on the CREATE path
    only. A record updating its own note must not be classified as a
    duplicate of itself and folded into it."""
    cfg = _cfg(project)
    stored = route_and_store(project, _engineering_record(), cfg=cfg)
    again = route_and_store(project, _engineering_record(
        memory_id=stored["memory_id"],
        root_cause="missing prefetch guard on the lfps detect synchronizer, re-derived after a re-audit",
        fix="add a two-flop synchronizer and re-time lfps_detect"), cfg=cfg)
    assert again["memory_id"] == stored["memory_id"]

    vault = again["vault_write"]
    assert vault["ok"] is True
    assert "dedup_classification" not in vault
    assert "folded_into" not in vault
    notes = _engineering_notes(project)
    assert len(notes) == 1
    _, body = mv.parse_note_markdown(notes[0].read_text(encoding="utf-8"))
    assert "re-time lfps_detect" in mv._body_to_sections(body)["Fix"]


def test_a_dedup_failure_never_stops_the_note_from_being_written(project, monkeypatch):
    """A dedup problem must never cost real verified knowledge: an
    unclassifiable candidate is written normally, not dropped."""
    cfg = _cfg(project)

    def _boom(*a, **kw):
        raise RuntimeError("vault scan exploded")

    monkeypatch.setattr(memory_dedup, "classify_note_candidate", _boom)
    result = route_and_store(project, _engineering_record(), cfg=cfg)
    assert result["vault_write"]["ok"] is True
    assert "dedup_classification" not in result["vault_write"]
    assert len(_engineering_notes(project)) == 1


# ---------------------------------------------------------------------------
# Phase 9 -- `protocol` is a HARD filter on the JSON MemoryStore too
# ---------------------------------------------------------------------------

def test_protocol_filters_rather_than_only_ranking_alongside_another_filter(project):
    """It used to add +3 to relevance only, so it excluded a non-matching
    record ONLY when nothing else in the query cleared the relevance floor:
    `--protocol USB3 --level engineering` returned every engineering-tier
    record whatever its protocol. The vault mirror's own search() has always
    treated protocol as a hard filter; the two backends now agree."""
    store = MemoryStore(project)
    store.add("engineering", {"memory_id": "MEM-USB3", "protocol": "USB3", "title": "lfps stall"})
    store.add("engineering", {"memory_id": "MEM-PCIE", "protocol": "PCIe", "title": "ltssm loop"})
    store.add("engineering", {"memory_id": "MEM-NONE", "title": "no protocol at all"})
    r = MemoryRetriever(store)

    def ids(hits):
        return sorted(h["memory"]["memory_id"] for h in hits)

    assert ids(r.search({"protocol": "USB3", "level": "engineering"})) == ["MEM-USB3"]
    assert ids(r.search({"protocol": "USB3"})) == ["MEM-USB3"]
    assert ids(r.search({"level": "engineering"})) == ["MEM-NONE", "MEM-PCIE", "MEM-USB3"]
    # A record with no protocol is not reachable by the literal string "none".
    assert r.search({"protocol": "None", "level": "engineering"}) == []
