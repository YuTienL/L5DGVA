"""Knowledge Layer edge tests (2026-09-04, governance-architecture gap close).

These are CONNECTION tests, not per-component tests: `test_memory_vault.py`
already proves `FileSystemMarkdownAdapter` writes Markdown and that
`_commit_vault_change()` can commit, and `test_evidence_db.py` already proves
`EvidenceStore` stores failure signatures. What was never proven -- and what
a fresh audit of the layered architecture diagram found genuinely missing --
is that the two edges DRAWN OUT of the Knowledge Layer actually carry
traffic on this project:

  1. Knowledge Layer -> Git. The commit mechanism was real and tested, but
     `memory.git_enabled` defaults to False (config.py) and this project's
     live `.dv-harness/config.json` had no `memory` key at all, so the real
     running vault inherited False: `.dv-harness/vault/.git` did not exist
     and no note had ever been committed. The code->git edge existed; the
     config->code edge that activates it for THIS project did not.

  2. Knowledge Layer -> DuckDB. `memory_vault.py`/`memory_router.py`
     contained no reference to `evidence_db` or `duckdb` in either
     direction, so the diagram's Knowledge-Layer DuckDB box had no
     implementation touching it at all. The Evidence Layer wrote
     `failure_signatures` rows that the Knowledge Layer's own
     prior-evidence search could never see.

Test 1 below asserts against this repository's REAL config file rather than
a fixture, because a fixture would prove nothing about whether the live
vault is actually git-backed -- that was precisely the audit finding.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from dv_harness import memory_vault as mv
from dv_harness.config import load_config
from dv_harness.memory import MemoryStore
from dv_harness.memory_router import route_and_store

REPO_ROOT = Path(__file__).resolve().parents[1]


def _tmp() -> Path:
    return Path(tempfile.mkdtemp())


def _rmtree(path: Path) -> None:
    def _on_rm_error(func, p, exc_info):
        # A vault with git_enabled=True contains a real .git tree whose
        # object files are read-only on Windows -- plain rmtree() raises
        # PermissionError on them (the exact breakage config.py's
        # git_enabled comment documents), so clear the bit and retry.
        import os as _os
        import stat as _stat
        _os.chmod(p, _stat.S_IWRITE)
        func(p)

    shutil.rmtree(path, onerror=_on_rm_error)


def _cfg(vault: Path, *, git_enabled: bool) -> dict:
    return {"knowledge_center": {"enabled": False},
            "memory": {"provider": "hybrid", "vault_path": str(vault),
                       "obsidian_cli": "disabled", "git_enabled": git_enabled}}


# ---------------------------------------------------------------------------
# Edge 1: Knowledge Layer (Markdown) -> Git
# ---------------------------------------------------------------------------

def test_this_projects_live_config_actually_activates_vault_git():
    """The config->code edge, asserted against the REAL live config file.

    `load_config()` deep-merges over DEFAULT_CONFIG, so this passes only if
    `.dv-harness/config.json` genuinely carries `memory.git_enabled: true` --
    inheriting config.py's opt-in False default (the pre-fix state) fails it.
    """
    live = json.loads((REPO_ROOT / ".dv-harness" / "config.json").read_text(encoding="utf-8"))
    assert "memory" in live, "live config must declare a memory block, not silently inherit defaults"
    assert live["memory"]["git_enabled"] is True

    merged = load_config(REPO_ROOT)
    assert merged["memory"]["git_enabled"] is True
    # The rest of the block must still be the real defaults, not clobbered.
    assert merged["memory"]["provider"] == "hybrid"
    assert merged["memory"]["obsidian_cli"] == "auto"


def test_live_config_makes_get_active_provider_hand_back_a_git_backed_adapter():
    """`get_active_provider()` is the one function every real vault caller
    goes through (`memory_router._maybe_write_vault_note()`,
    `search_related_memory_for_debug()`). Built against this project's real
    merged config it must produce a git-enabled filesystem adapter -- the
    concrete link from "the config says true" to "the adapter will commit".

    Uses a tmp vault_path override so the assertion is about the config's
    git_enabled flag, never about mutating this repo's own vault.
    """
    if shutil.which("git") is None:
        pytest.skip("git not installed on this machine")
    tmp = _tmp()
    try:
        cfg = load_config(REPO_ROOT)
        cfg["memory"] = {**cfg["memory"], "vault_path": str(tmp / "vault")}
        provider = mv.get_active_provider(tmp, cfg)
        assert isinstance(provider, mv.HybridMemoryProvider)
        assert provider.filesystem.git_enabled is True
        assert (tmp / "vault" / ".git").is_dir()
    finally:
        _rmtree(tmp)


def test_route_and_store_end_to_end_produces_a_real_vault_git_commit():
    """The whole drawn chain in one call: Graph/Planner -> memory_router
    .route_and_store() -> memory_vault Markdown note -> real git commit ->
    `knowledge_commit_sha` written back onto the JSON MemoryStore record.

    Deliberately asserts the real commit SHA out of `git log`, not merely
    that a `.git` directory appeared -- an initialised-but-never-committed
    repo would satisfy the weaker check while leaving the edge dead.
    """
    if shutil.which("git") is None:
        pytest.skip("git not installed on this machine")
    tmp = _tmp()
    try:
        vault = tmp / "vault"
        result = route_and_store(tmp, {
            "kind": "job_result", "job_id": 4242, "pattern": "usb_ep0_descriptor",
            "protocol": "USB2", "verified": True,
            "title": "LSF job 4242 reconciled DV PASS",
        }, cfg=_cfg(vault, git_enabled=True))

        assert result["destination"] == "JOB_MEMORY"
        vault_write = result["vault_write"]
        assert vault_write["ok"] is True

        sha = vault_write.get("knowledge_commit_sha")
        assert sha, "a git-enabled vault write must return the real commit SHA it produced"

        log = subprocess.run(["git", "log", "--format=%H %s"], cwd=str(vault),
                             capture_output=True, text=True)
        assert log.returncode == 0
        assert sha in log.stdout, "the returned SHA must be a commit that really exists in the vault repo"
        assert "memory(USB2): LSF job 4242 reconciled DV PASS" in log.stdout

        # The note itself is inside that commit, not merely on disk.
        tracked = subprocess.run(["git", "show", "--name-only", "--format=", sha],
                                 cwd=str(vault), capture_output=True, text=True)
        assert vault_write["path"].replace("\\", "/") in tracked.stdout.replace("\\", "/")

        # Traceability write-back: the JSON MemoryStore record (the system of
        # record) points at that exact vault commit.
        stored = MemoryStore(tmp).get(result["memory_id"])
        assert stored is not None
        assert stored.get("knowledge_commit_sha") == sha
    finally:
        _rmtree(tmp)


def test_git_disabled_config_still_writes_markdown_but_never_a_repo():
    """The opt-in default stays honest: turning the flag off must leave a
    real note on disk and no git repository, so `git_enabled` is genuinely
    the switch that decides the edge rather than a decorative field."""
    tmp = _tmp()
    try:
        vault = tmp / "vault"
        result = route_and_store(tmp, {
            "kind": "job_result", "job_id": 99, "pattern": "p", "protocol": "USB2",
            "verified": True, "title": "no-git run",
        }, cfg=_cfg(vault, git_enabled=False))
        assert result["vault_write"]["ok"] is True
        assert (vault / result["vault_write"]["path"]).exists()
        assert result["vault_write"].get("knowledge_commit_sha") is None
        assert not (vault / ".git").exists()
    finally:
        _rmtree(tmp)


# ---------------------------------------------------------------------------
# Edge 2: Knowledge Layer -> DuckDB (Evidence Layer's failure_signatures)
# ---------------------------------------------------------------------------

def _seed_evidence_db_failure(root: Path, *, protocol: str, symptom: str,
                              memory_id: str, job_id: int) -> dict:
    """Seeds through the REAL Evidence-Layer write path
    (`EvidenceStore.insert_job_memory_record()`, exactly what
    `lsf_client._upsert_job_tier_memory_record()` calls) rather than a
    hand-written INSERT, so this test would break if that path stopped
    populating `failure_signatures`."""
    from dv_harness import evidence_db

    sig = mv.build_failure_signature(protocol=protocol, pattern="usb_ep0_descriptor",
                                     symptom=symptom, uvm_error_count=3,
                                     terminal_signature="UVM_FATAL", lsf_status="EXIT")
    with evidence_db.EvidenceStore(evidence_db.default_db_path(root)) as store:
        store.insert_job_memory_record({
            "memory_id": memory_id, "kind": "job_failure", "job_id": job_id,
            "pattern": "usb_ep0_descriptor", "scope": "ip", "title": symptom,
            "lsf_status": "EXIT", "uvm_error_count": 3, "uvm_fatal_count": 1,
            "terminal_signature": "UVM_FATAL", "failure_signature": sig,
        })
    return sig


def test_debug_search_merges_vault_notes_and_evidence_db_signatures():
    """THE closed gap: one `search_related_memory_for_debug()` call must
    surface BOTH stores for the same failure, each tagged with its origin.

    Before this fix the evidence-db half was structurally unreachable --
    nothing in memory_vault.py/memory_router.py opened evidence_db at all --
    so a Debug/RCA agent got the Markdown note and never learned this exact
    failure shape had already been recorded by the Evidence Layer.
    """
    pytest.importorskip("duckdb")
    tmp = _tmp()
    try:
        vault = tmp / "vault"
        fs = mv.FileSystemMarkdownAdapter(vault, git_enabled=False)
        fs.create({"id": "MEM-EP0DESC", "memory_level": "engineering", "protocol": "USB2",
                   "status": "ACTIVE", "confidence": "HIGH",
                   "failure": "ep0 descriptor stall",
                   "created": "2026-09-04T00:00:00+00:00",
                   "updated": "2026-09-04T00:00:00+00:00"},
                  sections={"Root Cause": "descriptor length mismatch"})

        _seed_evidence_db_failure(tmp, protocol="USB2", symptom="ep0 descriptor stall",
                                  memory_id="MEM-JOB-4242", job_id=4242)

        sig = mv.build_failure_signature(protocol="USB2", symptom="ep0 descriptor stall")
        result = mv.search_related_memory_for_debug(tmp, _cfg(vault, git_enabled=False), sig, limit=5)

        assert result["ok"] is True
        sources = {c["source"] for c in result["related_cases"]}
        assert sources == {"vault", "evidence_db"}, f"both stores must be represented, got {sources}"
        assert result["vault_count"] >= 1
        assert result["evidence_db_count"] >= 1
        assert result["count"] == len(result["related_cases"])

        vault_case = next(c for c in result["related_cases"] if c["source"] == "vault")
        assert vault_case["frontmatter"]["id"] == "MEM-EP0DESC"

        ev_case = next(c for c in result["related_cases"] if c["source"] == "evidence_db")
        assert ev_case["protocol"] == "USB2"
        assert ev_case["symptom"] == "ep0 descriptor stall"
        assert ev_case["occurrence_count"] == 1
        assert ev_case["sample_job_id"] == 4242
        assert ev_case["sample_memory_id"] == "MEM-JOB-4242"

        # Merged results must stay JSON-serialisable: `related_cases` is
        # embedded into real job-memory records and stage prompts, and
        # DuckDB hands back datetime objects for first_seen/last_seen.
        json.dumps(result)
    finally:
        _rmtree(tmp)


def test_evidence_db_occurrence_count_reaches_the_debug_search():
    """The value the vault genuinely cannot supply: the Evidence Layer's
    aggregated "we have hit this exact failure shape N times" counter. Two
    real job-failure records with the SAME signature must arrive at the
    Knowledge Layer as one row with occurrence_count 2."""
    pytest.importorskip("duckdb")
    tmp = _tmp()
    try:
        _seed_evidence_db_failure(tmp, protocol="PCIe", symptom="ltssm recovery loop",
                                  memory_id="MEM-JOB-1", job_id=1)
        _seed_evidence_db_failure(tmp, protocol="PCIe", symptom="ltssm recovery loop",
                                  memory_id="MEM-JOB-2", job_id=2)

        sig = mv.build_failure_signature(protocol="PCIe", symptom="ltssm recovery loop")
        result = mv.search_related_memory_for_debug(tmp, _cfg(tmp / "vault", git_enabled=False), sig)

        ev = [c for c in result["related_cases"] if c["source"] == "evidence_db"]
        assert len(ev) == 1, "the same failure shape must aggregate onto one row, not duplicate"
        assert ev[0]["occurrence_count"] == 2
    finally:
        _rmtree(tmp)


def test_debug_search_does_not_surface_a_different_protocols_signature():
    """Protocol is a hard filter on the evidence-db side exactly as it is on
    the vault side -- prior evidence from an unrelated protocol is noise, and
    surfacing it would violate "memory is prior knowledge" by inviting a
    cross-protocol root cause to look like a match."""
    pytest.importorskip("duckdb")
    tmp = _tmp()
    try:
        _seed_evidence_db_failure(tmp, protocol="PCIe", symptom="ltssm recovery loop",
                                  memory_id="MEM-JOB-9", job_id=9)
        sig = mv.build_failure_signature(protocol="USB2", symptom="ltssm recovery loop")
        result = mv.search_related_memory_for_debug(tmp, _cfg(tmp / "vault", git_enabled=False), sig)
        assert [c for c in result["related_cases"] if c["source"] == "evidence_db"] == []
    finally:
        _rmtree(tmp)


def test_missing_evidence_db_is_reported_honestly_and_never_created():
    """A project with no evidence database yet (this repo's own real state
    today) must get a truthful reason, an unaffected vault result, and NO
    database conjured into existence by a read-only prior-evidence lookup."""
    from dv_harness import evidence_db

    tmp = _tmp()
    try:
        vault = tmp / "vault"
        fs = mv.FileSystemMarkdownAdapter(vault, git_enabled=False)
        fs.create({"id": "MEM-ONLY-VAULT", "memory_level": "engineering", "protocol": "USB2",
                   "status": "ACTIVE", "confidence": "HIGH", "failure": "ep0 descriptor stall",
                   "created": "2026-09-04T00:00:00+00:00",
                   "updated": "2026-09-04T00:00:00+00:00"})

        sig = mv.build_failure_signature(protocol="USB2", symptom="ep0 descriptor stall")
        result = mv.search_related_memory_for_debug(tmp, _cfg(vault, git_enabled=False), sig)

        assert result["ok"] is True  # the vault half still worked
        assert result["evidence_db"]["ok"] is False
        assert result["evidence_db"]["reason"] == "EVIDENCE_DB_NOT_PRESENT"
        assert result["evidence_db_count"] == 0
        assert result["vault_count"] >= 1
        assert not evidence_db.default_db_path(tmp).exists()
    finally:
        _rmtree(tmp)


def test_evidence_db_read_is_read_only_and_leaves_no_new_tables():
    """Defence in depth: the Knowledge Layer's read must not migrate, create
    or otherwise mutate the Evidence Layer's store. Compares the real table
    list before and after a search, and asserts the file's own bytes are
    unchanged."""
    pytest.importorskip("duckdb")
    from dv_harness import evidence_db

    tmp = _tmp()
    try:
        _seed_evidence_db_failure(tmp, protocol="USB2", symptom="ep0 descriptor stall",
                                  memory_id="MEM-JOB-7", job_id=7)
        db_path = evidence_db.default_db_path(tmp)

        def _tables():
            with evidence_db.EvidenceStore(db_path, read_only=True) as s:
                return sorted(r[0] for r in s.query("SHOW TABLES"))

        before, before_bytes = _tables(), db_path.read_bytes()
        sig = mv.build_failure_signature(protocol="USB2", symptom="ep0 descriptor stall")
        assert mv.search_evidence_db_failure_signatures(tmp, sig)["ok"] is True
        assert _tables() == before
        assert db_path.read_bytes() == before_bytes
    finally:
        _rmtree(tmp)


def test_stage_prompt_renders_an_evidence_db_case_with_real_content():
    """The far end of the edge: whatever `search_related_memory_for_debug()`
    merges has to survive `build_stage_prompt()`'s rendering, or the Debug
    agent never actually sees it. An evidence_db row has no `frontmatter`
    and no `note_id`, so the vault-shaped renderer emitted a content-free
    "- [?]" line for it -- the case would reach the prompt and say nothing.
    """
    from dv_harness.prompts import build_stage_prompt

    cases = [
        {"source": "vault", "note_id": "MEM-EP0DESC",
         "frontmatter": {"id": "MEM-EP0DESC", "failure": "ep0 descriptor stall"}},
        {"source": "evidence_db", "signature_key": "abcdef0123456789",
         "protocol": "USB2", "symptom": "ep0 descriptor stall",
         "root_cause_hint": "descriptor length mismatch", "occurrence_count": 4},
    ]
    prompt = build_stage_prompt("FAILURE_RECOVERY", "state", "goal", vault_related_cases=cases)

    assert "- [MEM-EP0DESC] ep0 descriptor stall" in prompt
    assert "sig:abcdef012345" in prompt
    assert "descriptor length mismatch" in prompt
    assert "4" in prompt.split("sig:abcdef012345")[1].split("\n")[0]
    assert "- [?]" not in prompt


def test_stage_prompt_still_renders_untagged_vault_cases_unchanged():
    """Backward compatibility: a case carrying no `source` (every caller's
    shape before 2026-09-04) must render exactly as it always did."""
    from dv_harness.prompts import build_stage_prompt

    prompt = build_stage_prompt("FAILURE_RECOVERY", "state", "goal", vault_related_cases=[
        {"note_id": "MEM-OLD", "frontmatter": {"id": "MEM-OLD", "failure": "legacy shape"}}])
    assert "- [MEM-OLD] legacy shape" in prompt


def test_search_never_raises_when_the_evidence_db_is_corrupt():
    """A damaged evidence store must degrade to "no prior evidence from
    there", never break a real debug attempt -- the same non-negotiable
    ordering `_maybe_write_vault_note()` already establishes for vault
    writes."""
    from dv_harness import evidence_db

    tmp = _tmp()
    try:
        db_path = evidence_db.default_db_path(tmp)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        db_path.write_bytes(b"this is not a duckdb file at all")

        sig = mv.build_failure_signature(protocol="USB2", symptom="ep0 descriptor stall")
        ev = mv.search_evidence_db_failure_signatures(tmp, sig)
        assert ev["ok"] is False
        assert ev["reason"] in ("EVIDENCE_DB_UNAVAILABLE", "EVIDENCE_DB_QUERY_FAILED")
        assert ev["results"] == []

        result = mv.search_related_memory_for_debug(tmp, _cfg(tmp / "vault", git_enabled=False), sig)
        assert result["related_cases"] == []
        assert "error" not in result  # degraded, not failed
    finally:
        _rmtree(tmp)
