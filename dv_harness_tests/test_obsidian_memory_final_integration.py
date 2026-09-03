"""Final integration test suite for the Obsidian+Git/Markdown Hybrid
Engineering Memory integration (Phase 22 of the 25-phase spec, last
workstream). This file is NOT a re-implementation of the underlying
mechanics -- every one of those already has real, focused unit tests in
`test_memory_vault.py` / `test_memory_dedup.py` / `test_memory_security.py`
/ `test_memory_doctor.py` / `test_cli_memory_commands.py` /
`test_debug_flow_memory.py` / `test_session_and_info.py` (Workstreams 1-3,
all still passing -- see `.work/obsidian-memory-*-report.md`).

This file exists to satisfy Phase 22's own explicit requirement: "build/
confirm real tests for all 14 required cases" as one clearly-enumerated,
independently-runnable checklist a reader can map 1:1 against the spec's own
numbered list, using the REAL modules built by Workstreams 1-3 end to end
(never a second, parallel mock implementation of any of them). Every test
below is a genuine call into `dv_harness.memory_vault` /
`dv_harness.memory_router` / `dv_harness.memory_dedup` /
`dv_harness.memory_security` / `dv_harness.session_snapshot` against a real
temp project directory -- no hardcoded/asserted-true results.

Case 2 ("Obsidian CLI exists -> adapter PASS") is explicitly a SIMULATED
case, called out as such in both the test name and its body: this
development machine has no real obsidian-cli/obsidian binary installed
(confirmed live by case 1's own unmocked probe), so this is the only one of
the 14 cases that cannot be exercised against a genuinely-installed CLI on
this machine -- it monkeypatches `shutil.which`/`subprocess.run` to prove
`detect_obsidian_cli()` is a real, general probe (not hardcoded to return
False) and would correctly flip to `installed: True` on a machine that has
one.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from dv_harness import memory_dedup, memory_router, memory_security, memory_vault as mv
from dv_harness import session_snapshot as snap


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def project(tmp_path) -> Path:
    root = tmp_path / "proj"
    (root / ".dv-harness").mkdir(parents=True)
    return root


@pytest.fixture()
def cfg_no_git() -> dict:
    # Real, non-empty cfg (so router additive behaviors like vault
    # write-through actually run) but with git disabled -- this repo's own
    # evidence-driven default (see obsidian-memory-core-report.md's
    # regression writeup: git_enabled=True broke Windows rmtree cleanup in
    # exactly this kind of temp-dir test).
    return {"memory": {"provider": "hybrid", "vault_path": "", "obsidian_cli": "auto", "git_enabled": False},
            "knowledge_center": {"enabled": False}}


def _make_engineering_record(protocol="USB", root_cause="phy clock domain crossing missing sync flop",
                              rc_shape="finding_consolidation"):
    verification = (
        {"single_sim": "PASS", "regression": "PASS", "reaudit": "CLEAN"}
        if rc_shape == "finding_consolidation" else
        {"targeted_reproducer_passed": True, "broader_regression_passed": True,
         "new_failures_introduced": False, "target_pre_fix_result": "FAIL",
         "target_post_fix_result": "PASS", "replay_equivalent": True}
    )
    return {
        "kind": "root_cause", "verified": True, "protocol": protocol, "scope": "LFPS",
        "title": f"{protocol} LFPS timeout root cause",
        "root_cause": root_cause,
        "fix": "add 2-flop synchronizer on phy_clk->core_clk lfps_detect signal",
        "symptoms": ["LFPS handshake timeout", "UVM_ERROR: polling.lfps timeout"],
        "evidence": ["waveform: lfps_detect glitches across clock domains", "rtl: no sync flop present"],
        "verification": verification,
    }


# ===========================================================================
# Case 1 -- no Obsidian CLI -> filesystem fallback PASS
# ===========================================================================

def test_case_01_no_obsidian_cli_falls_back_to_filesystem_pass(project, cfg_no_git):
    """Real (unmocked) probe on THIS machine: confirmed NOT_INSTALLED
    (matching the controller's own 2026-09-03 discovery), and the hybrid
    provider still performs a real, successful filesystem write."""
    report = mv.detect_obsidian_cli()
    assert report["installed"] is False
    assert report["status"] == "PARTIAL"  # never BLOCKED merely for absence

    provider = mv.get_active_provider(project, cfg_no_git)
    assert isinstance(provider, mv.HybridMemoryProvider)
    result = provider.create({"memory_level": "engineering", "protocol": "USB", "status": "ACTIVE",
                               "confidence": "HIGH"})
    assert result["ok"] is True
    # The real write landed on the filesystem adapter, not a no-op.
    note_path = provider.filesystem.vault_path / "06_Agent_Memory" / "Engineering" / f"{result['note_id']}.md"
    assert note_path.exists()


# ===========================================================================
# Case 2 -- Obsidian CLI exists -> adapter PASS (SIMULATED -- no real CLI
# installed on this machine, per the controller's own discovery)
# ===========================================================================

def test_case_02_obsidian_cli_present_is_detected_SIMULATED(monkeypatch):
    """SIMULATED: this machine genuinely has no obsidian-cli/obsidian binary
    (case 1 proves that with a real, unmocked probe). This test proves
    detect_obsidian_cli() is a real, general probe -- not a hardcoded
    `installed: False` -- by monkeypatching shutil.which/subprocess.run to
    simulate a real install and confirming detection correctly flips."""
    def fake_which(name):
        return f"/usr/local/bin/{name}" if name == "obsidian-cli" else None

    def fake_run(args, capture_output, text, timeout):
        return subprocess.CompletedProcess(args, 0, stdout="obsidian-cli 1.4.0\n", stderr="")

    monkeypatch.setattr(mv.shutil, "which", fake_which)
    monkeypatch.setattr(mv.subprocess, "run", fake_run)

    report = mv.detect_obsidian_cli()
    assert report["installed"] is True
    assert report["version"] == "obsidian-cli 1.4.0"
    assert report["executable"] == "/usr/local/bin/obsidian-cli"
    # Per Phase 8's own documented design: status stays PARTIAL even when
    # installed=True (no command contract has ever been verified against a
    # real instance) -- every operational method stays NOT_AVAILABLE.
    assert report["status"] == "PARTIAL"
    assert report["search"] == "NOT_AVAILABLE"

    adapter = mv.ObsidianAdapter()
    adapter._cached_report = None
    monkeypatch.setattr(mv, "detect_obsidian_cli", lambda: report)
    op_result = adapter.create({"id": "X"})
    assert op_result["ok"] is False
    assert op_result["status"] == "NOT_AVAILABLE"
    assert "ObsidianAdapter does not wire real operations" in op_result["reason"]
    assert op_result["fallback"] == "FileSystemMarkdownAdapter"


# ===========================================================================
# Case 3 -- create note
# ===========================================================================

def test_case_03_create_note(project, cfg_no_git):
    provider = mv.get_active_provider(project, cfg_no_git)
    result = provider.create(
        {"memory_level": "engineering", "protocol": "USB", "status": "ACTIVE", "confidence": "HIGH",
         "failure": "USB3 Polling.LFPS timeout"},
        sections={"Symptom": "LFPS handshake never completes", "Root Cause": "missing sync flop"},
    )
    assert result["ok"] is True
    assert result["note_id"].startswith("NOTE-")
    read_back = provider.read(result["note_id"])
    assert read_back["ok"] is True
    assert read_back["frontmatter"]["protocol"] == "USB"
    assert "LFPS handshake never completes" in read_back["body"]


# ===========================================================================
# Case 4 -- search note
# ===========================================================================

def test_case_04_search_note(project, cfg_no_git):
    provider = mv.get_active_provider(project, cfg_no_git)
    c1 = provider.create({"memory_level": "engineering", "protocol": "USB", "status": "ACTIVE",
                           "confidence": "HIGH", "failure": "LFPS timeout on polling"})
    provider.create({"memory_level": "engineering", "protocol": "PCIe", "status": "ACTIVE",
                      "confidence": "HIGH", "failure": "unrelated link training issue"})

    by_protocol = provider.search({"protocol": "USB"})
    assert by_protocol["ok"] is True
    assert any(r["note_id"] == c1["note_id"] for r in by_protocol["results"])
    assert all(r["frontmatter"]["protocol"] == "USB" for r in by_protocol["results"])

    by_text = provider.search({"text": "LFPS timeout"})
    assert any(r["note_id"] == c1["note_id"] for r in by_text["results"])


# ===========================================================================
# Case 5 -- update note
# ===========================================================================

def test_case_05_update_note(project, cfg_no_git):
    provider = mv.get_active_provider(project, cfg_no_git)
    c = provider.create({"memory_level": "engineering", "protocol": "USB", "status": "ACTIVE",
                          "confidence": "MEDIUM"},
                         sections={"Symptom": "original symptom", "Root Cause": "unknown"})
    upd = provider.update(c["note_id"], frontmatter_patch={"confidence": "HIGH"},
                           sections_patch={"Root Cause": "confirmed: missing sync flop"})
    assert upd["ok"] is True
    r = provider.read(c["note_id"])
    assert r["frontmatter"]["confidence"] == "HIGH"
    assert "missing sync flop" in r["body"]
    # partial patch preserves the untouched section
    assert "original symptom" in r["body"]
    # identity is immutable across a patch
    assert r["frontmatter"]["id"] == c["note_id"]


# ===========================================================================
# Case 6 -- YAML parse (frontmatter round-trip, including special chars)
# ===========================================================================

def test_case_06_yaml_frontmatter_parse_round_trip():
    fm = {
        "id": "NOTE-ABC123", "memory_level": "engineering", "protocol": "USB",
        "status": "ACTIVE", "confidence": "HIGH", "created": "2026-09-03T00:00:00+00:00",
        "updated": "2026-09-03T00:00:00+00:00",
        "failure": "colon: in value, and \"quotes\" plus\nnewline",
        "tags": ["usb", "lfps", "polling"],
        "rtl_sha": None,
    }
    rendered = mv.render_note_markdown(fm, {"Symptom": "s"})
    parsed_fm, body = mv.parse_note_markdown(rendered)
    assert parsed_fm["id"] == fm["id"]
    assert parsed_fm["failure"] == fm["failure"]
    assert parsed_fm["tags"] == fm["tags"]
    assert parsed_fm["rtl_sha"] is None
    assert "## Symptom" in body

    # A note whose frontmatter is missing the closing delimiter is honestly
    # unparsed (used by memory_doctor's invalid_yaml check).
    broken = "---\nid: NOTE-X\nno closing delimiter at all\n"
    fm2, body2 = mv.parse_note_markdown(broken)
    assert fm2 == {}
    assert body2 == broken


# ===========================================================================
# Case 7 -- wiki link (create, traverse forward + backlinks)
# ===========================================================================

def test_case_07_wiki_link_forward_and_backlinks(project, cfg_no_git):
    provider = mv.get_active_provider(project, cfg_no_git)
    source = provider.create({"memory_level": "engineering", "protocol": "USB", "status": "ACTIVE",
                               "confidence": "HIGH", "failure": "prior related LFPS issue"})
    linked = provider.create(
        {"memory_level": "engineering", "protocol": "USB", "status": "ACTIVE", "confidence": "HIGH",
         "failure": "USB3 Polling.LFPS timeout"},
        sections={"Related Knowledge": f"- [[{source['note_id']}]]"},
    )
    links = provider.list_links(linked["note_id"])
    assert links["ok"] is True
    assert source["note_id"] in links["forward_links"]

    back = provider.list_links(source["note_id"])
    assert linked["note_id"] in back["backlinks"]


# ===========================================================================
# Case 8 -- memory promotion (Engineering -> Organizational, full real gate)
# ===========================================================================

def test_case_08_memory_promotion_engineering_to_organizational(project, cfg_no_git):
    rec = _make_engineering_record()
    result = memory_router.route_and_store(project, rec, cfg=cfg_no_git)
    assert result["destination"] == "ENGINEERING_MEMORY"
    memory_id = result["memory_id"]

    # A single creation cleared the qualitative + confidence gates but has
    # NOT yet been confirmed by an independent second run -- the real
    # "no unverified/single-PASS jump to Organizational" guarantee.
    high_conf_inputs = dict(independent_sources_count=3, evidence_refs_verified=True,
                             counter_evidence_count=0, multi_agent_consensus_count=2)
    first_try = memory_router.promote_to_organizational(project, memory_id, high_conf_inputs, cfg=cfg_no_git)
    assert first_try["promoted"] is False
    assert first_try["reason"] == "INSUFFICIENT_CONFIRMATION"
    assert first_try["confirmation_count"] == 0

    # Two further independent runs re-deriving the SAME protocol/root_cause
    # are real confirmations (memory_router._add_or_confirm_engineering),
    # reaching ORGANIZATIONAL_MIN_CONFIRMATIONS (2) -- one confirmation call
    # alone (count=1) is still correctly insufficient.
    for _ in range(2):
        confirm_result = memory_router.route_and_store(project, _make_engineering_record(), cfg=cfg_no_git)
        assert confirm_result.get("confirmed_existing") is True

    second_try = memory_router.promote_to_organizational(project, memory_id, high_conf_inputs, cfg=cfg_no_git)
    # A genuine 3-gate PASS never sets "promoted": True (only "promoted":
    # False on a gate rejection, as above) -- success is signaled by
    # "destination" being present, per promote_to_organizational()'s own
    # real contract (see route_and_store()'s return shape it delegates to).
    assert "promoted" not in second_try
    assert second_try["destination"] == "ORGANIZATIONAL_MEMORY"
    assert second_try["promotion_gate"]["confidence_result"]["level"] == "HIGH"

    # A record whose evidence never clears the qualitative gate is honestly rejected.
    unverified = memory_router.route_and_store(
        project,
        {"kind": "root_cause", "verified": True, "protocol": "PCIe", "scope": "x",
         "root_cause": "unverified guess", "verification": {}},
        cfg=cfg_no_git,
    )
    bad_try = memory_router.promote_to_organizational(project, unverified["memory_id"], high_conf_inputs,
                                                        cfg=cfg_no_git)
    assert bad_try["promoted"] is False
    assert bad_try["reason"] == "QUALITATIVE_GATE_FAILED"


# ===========================================================================
# Case 9 -- duplicate detection (Phase 18 dedup, before write)
# ===========================================================================

def test_case_09_duplicate_detection(project, cfg_no_git):
    candidate = {"protocol": "USB", "failure_signature": "endpoint stall on bulk transfer",
                 "root_cause": "phy clock domain crossing missing sync flop",
                 "configuration": "high-speed mode, 3 endpoints",
                 "error_pattern": "UVM_ERROR timeout waiting for ACK"}
    fresh = memory_dedup.classify_note_candidate(project, candidate, cfg=cfg_no_git)
    assert fresh["classification"] == "NEW"

    provider = mv.get_active_provider(project, cfg_no_git)
    provider.create(
        {"memory_level": "engineering", "protocol": "USB", "status": "ACTIVE", "confidence": "HIGH",
         "failure": candidate["failure_signature"]},
        sections={"Root Cause": candidate["root_cause"], "Context": candidate["configuration"],
                   "Symptom": candidate["error_pattern"]},
    )

    exact_dup = memory_dedup.classify_note_candidate(project, candidate, cfg=cfg_no_git)
    assert exact_dup["classification"] == "DUPLICATE"

    different_protocol = dict(candidate, protocol="PCIe")
    unrelated = memory_dedup.classify_note_candidate(project, different_protocol, cfg=cfg_no_git)
    assert unrelated["classification"] != "DUPLICATE"  # hard protocol gate


# ===========================================================================
# Case 10 -- invalid note rejection (schema PARTIAL when a required field is
# missing; router REJECTs a credential-shaped record outright)
# ===========================================================================

def test_case_10_invalid_note_rejection(project, cfg_no_git):
    # (a) a note missing a MEMORY_NOTE_REQUIRED_FIELDS value is honestly
    # flagged schema_status=PARTIAL on the note itself, never silently
    # written as if it were complete.
    provider = mv.get_active_provider(project, cfg_no_git)
    incomplete = provider.create({"memory_level": "engineering", "status": "ACTIVE"})  # no protocol/confidence
    assert incomplete["validation"]["schema_status"] == "PARTIAL"
    assert "protocol" in incomplete["validation"]["missing_required"]
    r = provider.read(incomplete["note_id"])
    assert r["frontmatter"]["schema_status"] == "PARTIAL"

    # (b) route_memory() hard-REJECTs a credential/secret-shaped record --
    # it must never even reach the vault.
    with pytest.raises(ValueError, match="rejected"):
        memory_router.route_and_store(project, {"kind": "password", "value": "hunter2"}, cfg=cfg_no_git)


# ===========================================================================
# Case 11 -- secret redaction
# ===========================================================================

def test_case_11_secret_redaction(project, cfg_no_git):
    provider = mv.get_active_provider(project, cfg_no_git)
    result = provider.create(
        {"memory_level": "engineering", "protocol": "USB", "status": "ACTIVE", "confidence": "HIGH",
         "failure": "endpoint stall on VCPW=hunter2secret bulk transfer"},
    )
    assert result["ok"] is True
    assert any(f["type"] == "vc_password" for f in result["secrets_redacted"])
    r = provider.read(result["note_id"])
    assert "hunter2secret" not in r["frontmatter"]["failure"]
    assert "VCPW=***REDACTED-VC_PASSWORD***" in r["frontmatter"]["failure"]
    assert r["frontmatter"]["secrets_redacted"] is True

    # Idempotency: re-detecting the already-redacted marker must never
    # re-flag it as a fresh secret (the real bug found/fixed by Workstream 2).
    assert memory_security.detect_secrets(r["frontmatter"]["failure"]) == []

    # An update that reintroduces a raw secret is redacted too (create() and
    # update() both redact before writing, never only on first write).
    provider.update(result["note_id"], frontmatter_patch={"failure": "PASSWORD=anothersecret123 in log"})
    r2 = provider.read(result["note_id"])
    assert "anothersecret123" not in r2["frontmatter"]["failure"]


# ===========================================================================
# Case 12 -- git metadata (opt-in git integration: init, commit, real SHA)
# ===========================================================================

def test_case_12_git_metadata(project, tmp_path, monkeypatch):
    if not mv.shutil.which("git"):
        pytest.skip("git not installed on this machine")
    git_cfg = {"memory": {"provider": "hybrid", "vault_path": "", "obsidian_cli": "auto", "git_enabled": True},
               "knowledge_center": {"enabled": False}}
    rec = _make_engineering_record(protocol="Ethernet")
    result = memory_router.route_and_store(project, rec, cfg=git_cfg)
    assert result["destination"] == "ENGINEERING_MEMORY"
    vault_write = result["vault_write"]
    assert vault_write["ok"] is True
    assert vault_write.get("knowledge_commit_sha")
    sha = vault_write["knowledge_commit_sha"]
    assert len(sha) == 40 and all(c in "0123456789abcdef" for c in sha)

    # A real git log entry exists, with the spec's exact commit-message format.
    vault_path = mv.resolve_vault_path(project, git_cfg)
    log = subprocess.run(["git", "log", "--oneline", "-1"], cwd=str(vault_path),
                          capture_output=True, text=True)
    assert log.returncode == 0
    assert f"memory(Ethernet):" in log.stdout

    # The SHA was written back onto the underlying JSON MemoryStore record too.
    from dv_harness.memory import MemoryStore
    mem = MemoryStore(project).get(result["memory_id"])
    assert mem.get("knowledge_commit_sha") == sha


# ===========================================================================
# Case 13 -- session save
# ===========================================================================

def test_case_13_session_save(project):
    dvh = project / ".dv-harness"
    (dvh / "react" / "FAILURE_RECOVERY").mkdir(parents=True)
    (dvh / "state.json").write_text(json.dumps({
        "current_stage": "FAILURE_RECOVERY", "project": "USB3_Polling_Demo",
        "git_sha": "deadbeef", "overall_status": "IN_PROGRESS",
    }), encoding="utf-8")
    (dvh / "react" / "FAILURE_RECOVERY" / "iteration_001.json").write_text(json.dumps({
        "reason_summary": "LFPS timeout likely a CDC issue",
        "evidence": ["waveform glitch across clock domains"],
        "confidence": "MEDIUM",
        "next_action": "add targeted sync-flop reproducer",
    }), encoding="utf-8")

    manifest = snap.save_session(project, name="phase22-case13", note="test save")
    assert manifest["current_stage"] == "FAILURE_RECOVERY"
    assert manifest["current_project"] == "USB3_Polling_Demo"
    assert manifest["current_hypothesis"] == "LFPS timeout likely a CDC issue"
    assert manifest["current_confidence"] == "MEDIUM"
    assert manifest["pending_action"] == "add targeted sync-flop reproducer"
    saved_manifest_path = dvh / "sessions" / "phase22-case13" / "session_manifest.json"
    assert saved_manifest_path.exists()


# ===========================================================================
# Case 14 -- session restore
# ===========================================================================

def test_case_14_session_restore(project):
    dvh = project / ".dv-harness"
    (dvh / "react" / "FAILURE_RECOVERY").mkdir(parents=True)
    (dvh / "state.json").write_text(json.dumps({
        "current_stage": "FAILURE_RECOVERY", "project": "USB3_Polling_Demo", "git_sha": "deadbeef",
    }), encoding="utf-8")
    (dvh / "react" / "FAILURE_RECOVERY" / "iteration_001.json").write_text(json.dumps({
        "reason_summary": "LFPS timeout likely a CDC issue", "evidence": ["waveform glitch"],
        "confidence": "MEDIUM", "next_action": "add targeted sync-flop reproducer",
    }), encoding="utf-8")
    snap.save_session(project, name="phase22-case14", note="pre-restore")

    # mutate live state after the save
    (dvh / "state.json").write_text(json.dumps({"current_stage": "RE_AUDIT", "project": "changed"}),
                                     encoding="utf-8")

    restored = snap.restore_session(project, "phase22-case14", backup_current=True)
    assert restored["restored"] == "phase22-case14"
    assert restored["auto_backup"] is not None  # the live state was auto-backed-up first
    live_state = json.loads((dvh / "state.json").read_text(encoding="utf-8"))
    assert live_state["current_stage"] == "FAILURE_RECOVERY"
    assert live_state["project"] == "USB3_Polling_Demo"
    assert "LFPS timeout likely a CDC issue" in restored["resume_summary"]
    assert "add targeted sync-flop reproducer" in restored["resume_summary"]
