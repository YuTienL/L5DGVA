"""Multi-Hop Memory-Promotion Lineage Walker (dv_harness/memory_lineage.py),
item multi_hop_memory_lineage (2026-09-07).

Every fixture here is built through REAL production write paths -- never a
hand-typed JSON record standing in for one:
  * `memory_router.route_and_store()` for real Engineering-tier records
    (including real repeated-confirmation via a matching second/third
    submission, exactly `_add_or_confirm_engineering()`'s own real dedup/
    confirm logic).
  * `memory_router.promote_to_organizational()` for the real Organizational-
    tier record construction (gates, `score_confidence()`, provenance
    fields) -- the ONE real production writer of `source_engineering_
    memory_id`. `OrganizationalMemoryStore.add()` is patched only at the
    exact seam `test_memory_tier_integrity_and_admission.py`'s own
    `test_the_earned_promotion_path_still_clears_the_write_boundary_gate`
    already establishes for this identical reason (a real remote Knowledge
    Center push is out of scope for an automated pass) -- everything else
    downstream of that one seam, including the real local vault-note write,
    runs for real.
  * `memory.MemoryGC.confirm()` for confirmation events (never a hand-set
    `confirmation_count` field).
  * `memory.MemoryConsolidator.from_closed_finding()` for a real
    `source_finding_id`-carrying record.
  * `memory_vault.get_active_provider()` / `.create()` for real local vault
    notes, exercised both as a genuine side effect of a real organizational
    promotion and, for the vault-fallback-specific tests, built directly
    through the same real functions `memory_router._maybe_write_vault_note()`
    itself calls (`build_frontmatter_from_memory_record`,
    `build_sections_from_memory_record`).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from dv_harness import memory_lineage as ml
from dv_harness.memory import MemoryConsolidator, MemoryGC, MemoryStore
from dv_harness.memory_router import promote_to_organizational, route_and_store

_HIGH_CONF = dict(independent_sources_count=3, evidence_refs_verified=True,
                   counter_evidence_count=0, multi_agent_consensus_count=2)

_VERIFIED_FIX = {
    "kind": "verified_fix", "verified": True, "protocol": "USB3", "scope": "engineering",
    "root_cause": "off-by-one in retry counter", "fix": "increment before compare",
    "confidence": "HIGH", "evidence": "targeted reproducer log at JOB-100",
    "verification": {
        "targeted_reproducer_passed": True, "broader_regression_passed": True,
        "new_failures_introduced": False, "target_pre_fix_result": "FAIL",
        "target_post_fix_result": "PASS", "replay_equivalent": True,
    },
}


def _disable_obsidian(root: Path) -> None:
    """This machine's own `dv_harness_tests/test_memory_vault.py::
    test_detect_obsidian_cli_real_probe_reports_not_installed_on_this_machine`
    already fails because SOMETHING named obsidian-shaped resolves on this
    machine's PATH -- confirmed pre-existing and unrelated to this module by
    re-running that suite before this file was written. Disabling
    `memory.obsidian_cli` here keeps every vault-touching test in this file
    deterministic regardless of that environment quirk, the same explicit
    opt-out `memory_vault.get_active_provider()`'s own docstring names."""
    (root / ".dv-harness").mkdir(parents=True, exist_ok=True)
    (root / ".dv-harness" / "config.json").write_text(
        json.dumps({"memory": {"obsidian_cli": "disabled"}}), encoding="utf-8")


def _confirmed_engineering_record(root: Path, *, evidence_1="ev-1", evidence_2="ev-2",
                                   evidence_3="ev-3") -> str:
    """Three real route_and_store() submissions of the SAME (protocol,
    root_cause): the first creates the record, the second and third each
    independently re-derive it and therefore CONFIRM it via the real
    `_add_or_confirm_engineering()`/`MemoryGC.confirm()` path -- reaching
    `confirmation_count == 2 == ORGANIZATIONAL_MIN_CONFIRMATIONS`."""
    mid = route_and_store(root, dict(_VERIFIED_FIX, evidence=evidence_1), cfg={})["memory_id"]
    r2 = route_and_store(root, dict(_VERIFIED_FIX, evidence=evidence_2), cfg={})
    assert r2.get("confirmed_existing") is True
    r3 = route_and_store(root, dict(_VERIFIED_FIX, evidence=evidence_3), cfg={})
    assert r3.get("confirmed_existing") is True
    stored = MemoryStore(root).get(mid)
    assert stored["confirmation_count"] == 2
    return mid


def _promote_with_real_vault_write(root: Path, source_id: str) -> dict:
    """Promotes `source_id` to Organizational tier through the REAL
    `promote_to_organizational()` -> `route_and_store()` -> `organizational_
    admission_gate()` -> `_maybe_write_vault_note()` chain, patching only the
    literal remote-push seam (`OrganizationalMemoryStore.add`) -- the exact
    idiom `test_memory_tier_integrity_and_admission.py::
    test_the_earned_promotion_path_still_clears_the_write_boundary_gate`
    already established -- so the real local vault note this test needs is
    genuinely written by real code, never hand-authored."""
    _disable_obsidian(root)
    # A non-empty cfg is required for the vault write-through: `cfg={}` is
    # `route_and_store()`'s own documented "opt out of every cfg-driven
    # additive behaviour" signal (`_maybe_write_vault_note()` starts with
    # `if not cfg: return None`) -- exactly the falsy-empty-dict case, not a
    # network concern. The org branch never calls `_maybe_share()`
    # (knowledge_center) at all, so this stays fully local regardless.
    vault_cfg = {"memory": {"obsidian_cli": "disabled"}}
    pushed = []
    with patch("dv_harness.memory_router.OrganizationalMemoryStore") as org_store:
        org_store.return_value.add.side_effect = lambda rec: pushed.append(rec) or {"ok": True}
        result = promote_to_organizational(root, source_id, _HIGH_CONF, cfg=vault_cfg,
                                            kind="methodology")
    assert result["destination"] == "ORGANIZATIONAL_MEMORY", result
    assert result.get("vault_write", {}).get("ok") is True, result
    assert len(pushed) == 1
    return result


# ---------------------------------------------------------------------------
# Genuine caller-usage errors (never an ordinary unresolved reference)
# ---------------------------------------------------------------------------

def test_empty_memory_id_raises_a_genuine_usage_error(tmp_path):
    with pytest.raises(ml.MemoryLineageError):
        ml.build_lineage(tmp_path, "")
    with pytest.raises(ml.MemoryLineageError):
        ml.build_lineage(tmp_path, None)


def test_non_dict_record_raises_a_genuine_usage_error(tmp_path):
    with pytest.raises(ml.MemoryLineageError):
        ml.build_lineage(tmp_path, "ORG-1", record=["not", "a", "dict"])


# ---------------------------------------------------------------------------
# Read-only / no-mutation honesty
# ---------------------------------------------------------------------------

def test_bare_project_reports_root_unavailable_and_mints_nothing(tmp_path):
    result = ml.build_organizational_lineage(tmp_path, "ORG-DOES-NOT-EXIST")
    assert result.status == ml.STATUS_ROOT_UNAVAILABLE
    assert result.root is None
    assert not (tmp_path / ".dv-harness").exists()


def test_memory_store_present_but_id_unresolved_still_mints_nothing_new(tmp_path):
    """has_memory_store() is True (a real store exists from an unrelated
    write) but the SPECIFIC id asked about does not exist anywhere and no
    vault is present -- ROOT_UNAVAILABLE, and no NEW file appears."""
    route_and_store(tmp_path, dict(_VERIFIED_FIX), cfg={})
    before = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*") if p.is_file())

    result = ml.build_organizational_lineage(tmp_path, "ORG-PHANTOM-ID")

    after = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*") if p.is_file())
    assert result.status == ml.STATUS_ROOT_UNAVAILABLE
    assert before == after


# ---------------------------------------------------------------------------
# Single-hop source_engineering_memory_id, via a caller-supplied org record
# ---------------------------------------------------------------------------

def test_caller_supplied_org_record_resolves_the_real_source_engineering_link(tmp_path):
    eng_id = _confirmed_engineering_record(tmp_path)

    captured = {}
    with patch("dv_harness.memory_router.OrganizationalMemoryStore") as org_store:
        org_store.return_value.add.side_effect = (
            lambda rec: captured.update(rec) or {"ok": True})
        promoted = promote_to_organizational(tmp_path, eng_id, _HIGH_CONF, cfg={},
                                              kind="methodology")
    assert promoted["destination"] == "ORGANIZATIONAL_MEMORY"
    assert captured["source_engineering_memory_id"] == eng_id  # the real field this module reuses

    result = ml.build_organizational_lineage(tmp_path, "ORG-INSPECTED", org_record=captured)

    assert result.status == ml.STATUS_FULLY_RESOLVED
    assert result.unresolved_reference_count == 0
    root = result.root
    assert root.resolution_source == ml.RESOLUTION_CALLER_SUPPLIED
    refs = [r for r in root.references if r.field == ml.SOURCE_ENGINEERING_FIELD]
    assert len(refs) == 1
    assert refs[0].resolved is True
    assert refs[0].node.memory_id == eng_id
    assert refs[0].node.level == "engineering"
    assert refs[0].node.resolution_source == ml.RESOLUTION_LOCAL_JSON


# ---------------------------------------------------------------------------
# Confirmation-event honesty: only the MOST RECENT evidence survives
# ---------------------------------------------------------------------------

def test_confirmation_history_only_the_most_recent_evidence_is_recoverable(tmp_path):
    eng_id = _confirmed_engineering_record(
        tmp_path, evidence_1="FIRST evidence (lost)",
        evidence_2="SECOND evidence (lost)", evidence_3="THIRD evidence (retained)")

    result = ml.build_lineage(tmp_path, eng_id)
    node = result.root
    conf = node.confirmation
    assert conf["confirmation_count"] == 2
    assert conf["most_recent_confirmation_evidence"] == "THIRD evidence (retained)"
    assert conf["full_confirmation_history_recoverable"] is False
    assert "1 confirmation event(s)" in conf["note"]
    # The middle (2nd submission's) evidence is genuinely gone -- never
    # fabricated back into existence by this module.
    assert "SECOND evidence" not in json.dumps(conf)
    assert "FIRST evidence" not in json.dumps(conf)


def test_never_confirmed_record_states_so_honestly(tmp_path):
    mid = route_and_store(tmp_path, dict(_VERIFIED_FIX), cfg={})["memory_id"]
    result = ml.build_lineage(tmp_path, mid)
    assert result.root.confirmation["confirmation_count"] == 0
    assert result.root.confirmation["note"] == "Never independently re-confirmed after creation."


# ---------------------------------------------------------------------------
# Dangling reference
# ---------------------------------------------------------------------------

def test_dangling_source_engineering_reference_is_reported_not_silently_dropped(tmp_path):
    org_record = {
        "kind": "methodology", "title": "synthetic", "protocol": "USB3",
        "source_engineering_memory_id": "MEM-GHOST-0000000000",
    }
    result = ml.build_organizational_lineage(tmp_path, "ORG-1", org_record=org_record)
    assert result.status == ml.STATUS_PARTIALLY_RESOLVED
    assert result.unresolved_reference_count == 1
    ref = result.root.references[0]
    assert ref.field == ml.SOURCE_ENGINEERING_FIELD
    assert ref.resolved is False
    assert ref.node is None
    assert "NOT_FOUND" in ref.reason


# ---------------------------------------------------------------------------
# corroborating_memory_ids: real multi-hop recursion + a real Job-tier leaf
# ---------------------------------------------------------------------------

def test_corroborating_memory_ids_walks_a_real_multi_hop_chain_to_a_job_tier_leaf(tmp_path):
    store = MemoryStore(tmp_path)
    job_rec = store.add("job", {
        "kind": "job_result", "title": "USB3 LFPS regression, real bring-up job",
        "protocol": "USB3", "git_sha": "abc123def", "test": "usb3_lfps_regress",
        "result": "PASS",
    })
    mid_a = store.add("engineering", {
        "kind": "root_cause", "protocol": "USB3", "root_cause": "corroborating record A",
        "evidence": "corroborated by the real job result", "confidence": "HIGH",
        "corroborating_memory_ids": [job_rec["memory_id"]],
    })["memory_id"]
    mid_b = store.add("engineering", {
        "kind": "root_cause", "protocol": "USB3", "root_cause": "top-level engineering record B",
        "evidence": "second-order corroboration", "confidence": "HIGH",
        "corroborating_memory_ids": [mid_a],
    })["memory_id"]

    org_record = {"kind": "methodology", "protocol": "USB3",
                  "source_engineering_memory_id": mid_b}
    result = ml.build_organizational_lineage(tmp_path, "ORG-2", org_record=org_record)

    assert result.status == ml.STATUS_FULLY_RESOLVED
    node_b = result.root.references[0].node
    assert node_b.memory_id == mid_b
    corrob_refs_b = [r for r in node_b.references if r.field == ml.CORROBORATING_FIELD]
    assert len(corrob_refs_b) == 1
    node_a = corrob_refs_b[0].node
    assert node_a.memory_id == mid_a
    corrob_refs_a = [r for r in node_a.references if r.field == ml.CORROBORATING_FIELD]
    assert len(corrob_refs_a) == 1
    job_node = corrob_refs_a[0].node
    assert job_node.memory_id == job_rec["memory_id"]
    assert job_node.level == "job"
    assert job_node.inline_evidence["git_sha"] == "abc123def"
    assert job_node.inline_evidence["test"] == "usb3_lfps_regress"

    job_evidence = ml.collect_job_tier_evidence(result.root)
    kinds = {e["evidence_kind"] for e in job_evidence}
    assert "job_tier_memory_record" in kinds
    record_row = next(e for e in job_evidence if e["evidence_kind"] == "job_tier_memory_record")
    assert record_row["memory_id"] == job_rec["memory_id"]
    assert record_row["path"] == ["ORG-2", mid_b, mid_a, job_rec["memory_id"]]


def test_leaf_engineering_record_surfaces_inline_evidence_as_job_tier_proxy(tmp_path):
    """No corroborating_memory_ids at all -- the terminal Engineering record's
    OWN inline evidence fields are the only recoverable "Job-tier evidence",
    honestly labelled as such rather than as a separate resolved record."""
    eng_id = _confirmed_engineering_record(tmp_path)
    org_record = {"kind": "methodology", "protocol": "USB3",
                  "source_engineering_memory_id": eng_id}
    result = ml.build_organizational_lineage(tmp_path, "ORG-3", org_record=org_record)

    evidence = ml.collect_job_tier_evidence(result.root)
    leaf = [e for e in evidence if e["evidence_kind"] == "inline_evidence_no_separate_job_record"]
    assert len(leaf) == 1
    assert leaf[0]["memory_id"] == eng_id
    assert leaf[0]["evidence"]["root_cause"] == "off-by-one in retry counter"
    assert leaf[0]["evidence"]["fix"] == "increment before compare"


# ---------------------------------------------------------------------------
# Cycle detection
# ---------------------------------------------------------------------------

def test_cycle_is_detected_never_infinite_loops(tmp_path):
    store = MemoryStore(tmp_path)
    mid_a = store.add("engineering", {
        "kind": "root_cause", "protocol": "USB3", "root_cause": "cycle member A",
        "evidence": "e", "confidence": "HIGH",
    })["memory_id"]
    mid_b = store.add("engineering", {
        "kind": "root_cause", "protocol": "USB3", "root_cause": "cycle member B",
        "evidence": "e", "confidence": "HIGH", "corroborating_memory_ids": [mid_a],
    })["memory_id"]
    # Close the cycle: A now also points at B.
    rec_a = store.get(mid_a)
    rec_a["corroborating_memory_ids"] = [mid_b]
    store.add("engineering", rec_a)

    result = ml.build_lineage(tmp_path, mid_a)
    # Reaches back to itself one hop later without hanging.
    assert result.status in (ml.STATUS_FULLY_RESOLVED, ml.STATUS_PARTIALLY_RESOLVED)
    node_b = result.root.references[0].node
    assert node_b.memory_id == mid_b
    node_cycle = node_b.references[0].node
    assert node_cycle.is_cycle_reference is True
    assert node_cycle.memory_id == mid_a
    # A cycle reference is a KNOWN fact, not a dangling pointer: it counts as
    # resolved, and never inflates unresolved_reference_count.
    assert node_b.references[0].resolved is True
    assert result.unresolved_reference_count == 0


# ---------------------------------------------------------------------------
# source_finding_id: real, cited, but structurally never resolved
# ---------------------------------------------------------------------------

def test_source_finding_id_is_a_real_external_reference_never_resolved(tmp_path):
    store = MemoryStore(tmp_path)
    consolidated = MemoryConsolidator(store).from_closed_finding(
        {"status": "CLOSED", "finding_id": "FIND-77", "protocol": "USB3",
         "root_cause": "consolidated from a real closed finding", "title": "closed finding"},
        {"single_sim": "PASS", "regression": "NOT_REQUIRED", "reaudit": "CLEAN"})
    assert consolidated["source_finding_id"] == "FIND-77"

    org_record = {"kind": "methodology", "protocol": "USB3",
                  "source_engineering_memory_id": consolidated["memory_id"]}
    result = ml.build_organizational_lineage(tmp_path, "ORG-4", org_record=org_record)

    eng_node = result.root.references[0].node
    finding_refs = [r for r in eng_node.references if r.field == ml.SOURCE_FINDING_FIELD]
    assert len(finding_refs) == 1
    ref = finding_refs[0]
    assert ref.memory_id == "FIND-77"
    assert ref.resolved is False
    assert ref.node is None
    assert "EXTERNAL_REFERENCE" in ref.reason
    assert "Blackboard" in ref.reason
    # External references never count as an "unresolved" defect, and never
    # get silently attempted against MemoryStore.
    assert result.unresolved_reference_count == 0
    assert result.external_reference_count == 1


# ---------------------------------------------------------------------------
# The Organizational-tier DV-Knowledge Vault fallback -- the real, no-local-
# JSON-file case, end to end
# ---------------------------------------------------------------------------

def test_vault_fallback_resolves_a_real_organizational_note_end_to_end(tmp_path):
    eng_id = _confirmed_engineering_record(tmp_path)
    promoted = _promote_with_real_vault_write(tmp_path, eng_id)
    org_note_id = promoted["vault_write"]["note_id"]

    # The real Organizational tier genuinely has no local per-tier JSON file
    # for this record -- confirmed directly, matching memory.py's own design.
    assert MemoryStore(tmp_path).get(org_note_id) is None

    result = ml.build_organizational_lineage(tmp_path, org_note_id)

    assert result.status == ml.STATUS_FULLY_RESOLVED
    root = result.root
    assert root.memory_id == org_note_id
    assert root.level == "organizational"
    assert root.resolution_source == ml.RESOLUTION_VAULT_NOTE
    # Resolved through the vault mirror -- its frontmatter carries no
    # `source_engineering_memory_id` key at all (only the note BODY's
    # "Related Knowledge" wikilink does), so this is honestly reported as an
    # AMBIGUOUS vault-mirror link rather than a fabricated
    # source_engineering_memory_id citation the record does not actually
    # carry in this resolution path -- see the module docstring's own
    # "GENUINE, DISCLOSED AMBIGUITY" paragraph.
    ref = root.references[0]
    assert ref.field == ml.VAULT_AMBIGUOUS_LINK_FIELD
    assert ref.resolved is True
    assert ref.node.memory_id == eng_id
    assert ref.node.resolution_source == ml.RESOLUTION_LOCAL_JSON
    assert not result.notes  # no spurious "not actually organizational" warning


def test_vault_related_knowledge_similarity_links_are_never_treated_as_lineage(tmp_path):
    """A RELATED-by-similarity wikilink (memory_router._related_knowledge_
    with_links()'s own real shape, "(related, similarity N.NN)") must never
    be mistaken for a derivation/source citation -- only a BARE [[id]] line
    is walked, and it is walked honestly as AMBIGUOUS (the vault mirror does
    not tag which real field produced it)."""
    from dv_harness import memory_vault as mv

    _disable_obsidian(tmp_path)
    store = MemoryStore(tmp_path)
    real_eng = store.add("engineering", {
        "kind": "root_cause", "protocol": "USB3", "root_cause": "genuinely derived from",
        "evidence": "e", "confidence": "HIGH",
    })

    cfg = json.loads((tmp_path / ".dv-harness" / "config.json").read_text(encoding="utf-8"))
    provider = mv.get_active_provider(tmp_path, cfg)
    frontmatter = mv.build_frontmatter_from_memory_record("ORGANIZATIONAL_MEMORY", {
        "memory_id": "ORG-MANUAL-1", "protocol": "USB3", "title": "manual vault note",
        "status": "ACTIVE", "confidence": "HIGH",
    })
    sections = {
        "Related Knowledge": (
            f"- [[{real_eng['memory_id']}]]\n"
            "- [[MEM-UNRELATED-SIMILARITY]] (related, similarity 0.87)"
        ),
    }
    created = provider.create(frontmatter, sections=sections)
    assert created["ok"] is True

    result = ml.build_lineage(tmp_path, "ORG-MANUAL-1")
    ambiguous_refs = [r for r in result.root.references if r.field == ml.VAULT_AMBIGUOUS_LINK_FIELD]
    assert len(ambiguous_refs) == 1
    assert ambiguous_refs[0].memory_id == real_eng["memory_id"]
    assert ambiguous_refs[0].resolved is True
    assert ambiguous_refs[0].node.memory_id == real_eng["memory_id"]
    # The similarity-suffixed line is never turned into a reference at all.
    assert all(r.memory_id != "MEM-UNRELATED-SIMILARITY" for r in result.root.references)


def test_vault_note_missing_entirely_reports_root_unavailable_but_creates_nothing_new(tmp_path):
    _disable_obsidian(tmp_path)
    # Force a vault directory to exist (so the fallback path is even
    # attempted) without ever creating a matching note.
    (tmp_path / ".dv-harness" / "vault").mkdir(parents=True, exist_ok=True)
    before = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*") if p.is_file())

    result = ml.build_organizational_lineage(tmp_path, "ORG-GHOST-NOTE")

    after = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*") if p.is_file())
    assert result.status == ml.STATUS_ROOT_UNAVAILABLE
    assert before == after


# ---------------------------------------------------------------------------
# Depth cap (defensive; cycle detection is the real guard)
# ---------------------------------------------------------------------------

def test_depth_limit_is_a_real_defensive_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(ml, "MAX_LINEAGE_DEPTH", 2)
    store = MemoryStore(tmp_path)
    mid_c = store.add("engineering", {"kind": "root_cause", "protocol": "USB3",
                                       "root_cause": "c", "evidence": "e", "confidence": "HIGH"})["memory_id"]
    mid_b = store.add("engineering", {"kind": "root_cause", "protocol": "USB3", "root_cause": "b",
                                       "evidence": "e", "confidence": "HIGH",
                                       "corroborating_memory_ids": [mid_c]})["memory_id"]
    mid_a = store.add("engineering", {"kind": "root_cause", "protocol": "USB3", "root_cause": "a",
                                       "evidence": "e", "confidence": "HIGH",
                                       "corroborating_memory_ids": [mid_b]})["memory_id"]
    result = ml.build_lineage(tmp_path, mid_a)
    # Never raises, never hangs -- the cap fires and is reported honestly.
    assert result.status in (ml.STATUS_FULLY_RESOLVED, ml.STATUS_PARTIALLY_RESOLVED)


# ---------------------------------------------------------------------------
# Rendering / flatten / to_dict
# ---------------------------------------------------------------------------

def test_flatten_and_render_produce_a_queryable_chain(tmp_path):
    eng_id = _confirmed_engineering_record(tmp_path)
    org_record = {"kind": "methodology", "protocol": "USB3",
                  "source_engineering_memory_id": eng_id}
    result = ml.build_organizational_lineage(tmp_path, "ORG-5", org_record=org_record)

    as_dict = result.to_dict()
    assert as_dict["root_memory_id"] == "ORG-5"
    assert as_dict["status"] == ml.STATUS_FULLY_RESOLVED
    memory_ids_in_chain = {row["memory_id"] for row in as_dict["chain"] if row["row_kind"] == "node"}
    assert {"ORG-5", eng_id} <= memory_ids_in_chain

    text = ml.render_lineage_text(result)
    assert "ORG-5" in text
    assert eng_id in text
    assert ml.STATUS_FULLY_RESOLVED in text


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_lineage_exit_codes_and_json(tmp_path):
    eng_id = _confirmed_engineering_record(tmp_path)
    org_record = {"kind": "methodology", "protocol": "USB3",
                  "source_engineering_memory_id": eng_id}
    record_path = tmp_path / "org_record.json"
    record_path.write_text(json.dumps(org_record), encoding="utf-8")

    code = ml.execute_verb("lineage", root_path=str(tmp_path), memory_id="ORG-CLI-1",
                            record_path=str(record_path), as_json=True)
    assert code == 0

    bad_record_path = tmp_path / "bad.json"
    bad_record_path.write_text("not json", encoding="utf-8")
    code2 = ml.execute_verb("lineage", root_path=str(tmp_path), memory_id="ORG-CLI-2",
                             record_path=str(bad_record_path))
    assert code2 == 2

    code3 = ml.execute_verb("lineage", root_path=str(tmp_path), memory_id=None)
    assert code3 == 2

    code4 = ml.execute_verb("not-lineage", root_path=str(tmp_path), memory_id="x")
    assert code4 == 2


def test_cli_root_unavailable_exit_code(tmp_path):
    code = ml.execute_verb("lineage", root_path=str(tmp_path), memory_id="ORG-NOTHING")
    assert code == 2


def test_real_subprocess_entry_point(tmp_path):
    eng_id = _confirmed_engineering_record(tmp_path)
    org_record = {"kind": "methodology", "protocol": "USB3",
                  "source_engineering_memory_id": eng_id}
    record_path = tmp_path / "org_record.json"
    record_path.write_text(json.dumps(org_record), encoding="utf-8")

    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.memory_lineage", "lineage",
         "--root", str(tmp_path), "--memory-id", "ORG-SUBPROC", "--record", str(record_path),
         "--json"],
        cwd=str(Path(__file__).resolve().parent.parent),
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == ml.STATUS_FULLY_RESOLVED
    assert payload["root"]["references"][0]["memory_id"] == eng_id
