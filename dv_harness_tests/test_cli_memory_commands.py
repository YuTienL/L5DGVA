"""Tests for the `dv-harness memory ...` CLI subcommand group -- Phase 20
of the Obsidian+Git/Markdown Hybrid Engineering Memory spec, Workstream 2 of
4. See dv_harness/cli.py's `pmem`/`pmem_sub` block.

Runs `dv_harness.cli.main()` in-process against a fresh --project-root
tmp_path, following the same monkeypatched-sys.argv pattern already
established by dv_harness_tests/test_self_tuning_cli.py.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

import dv_harness.cli as cli_mod
from dv_harness.memory import MemoryStore


def _run_cli(monkeypatch, tmp_path, args, capsys):
    monkeypatch.setattr(sys, "argv", ["dv-harness", "--project-root", str(tmp_path)] + args)
    try:
        rc = cli_mod.main()
    except SystemExit as e:
        rc = e.code
    out = capsys.readouterr().out
    return (rc if rc is not None else 0), out


def _add(monkeypatch, tmp_path, capsys, **kw):
    args = ["memory", "add", "--protocol", kw.get("protocol", "USB")]
    if kw.get("failure") is not None:
        args += ["--failure", kw["failure"]]
    if kw.get("root_cause") is not None:
        args += ["--root-cause", kw["root_cause"]]
    if kw.get("configuration") is not None:
        args += ["--configuration", kw["configuration"]]
    if kw.get("error_pattern") is not None:
        args += ["--error-pattern", kw["error_pattern"]]
    if kw.get("force"):
        args += ["--force"]
    return _run_cli(monkeypatch, tmp_path, args, capsys)


# --- status ------------------------------------------------------------------

def test_memory_status_reports_provider_and_zero_counts_on_fresh_vault(monkeypatch, tmp_path, capsys):
    rc, out = _run_cli(monkeypatch, tmp_path, ["memory", "status"], capsys)
    assert rc == 0
    data = json.loads(out)
    assert data["note_counts"]["total"] == 0
    assert data["provider_status"]["provider"] == "hybrid"
    assert data["config"]["provider"] == "hybrid"


# --- add / dedup / show / search ---------------------------------------------

def test_memory_add_writes_a_note_and_reports_new_classification(monkeypatch, tmp_path, capsys):
    rc, out = _add(monkeypatch, tmp_path, capsys,
                    failure="stall on bulk transfer", root_cause="missing sync flop",
                    configuration="hs mode", error_pattern="timeout waiting ACK")
    assert rc == 0
    data = json.loads(out)
    assert data["ok"] is True
    assert data["dedup_classification"] == "NEW"

    rc2, out2 = _run_cli(monkeypatch, tmp_path, ["memory", "status"], capsys)
    assert json.loads(out2)["note_counts"]["total"] == 1


def test_memory_add_redacts_a_secret_embedded_in_the_failure_field(monkeypatch, tmp_path, capsys):
    rc, out = _add(monkeypatch, tmp_path, capsys, failure="stall VCPW=realsecretvalue during bulk transfer")
    assert rc == 0
    data = json.loads(out)
    assert data["ok"] is True
    assert data.get("secrets_redacted")
    note_id = data["note_id"]

    rc2, out2 = _run_cli(monkeypatch, tmp_path, ["memory", "show", note_id], capsys)
    shown = json.loads(out2)
    assert "realsecretvalue" not in json.dumps(shown)


def test_memory_add_refuses_a_duplicate_without_force(monkeypatch, tmp_path, capsys):
    kwargs = dict(failure="stall on bulk transfer", root_cause="missing sync flop",
                  configuration="hs mode", error_pattern="timeout waiting ACK")
    rc1, _ = _add(monkeypatch, tmp_path, capsys, **kwargs)
    assert rc1 == 0

    rc2, out2 = _add(monkeypatch, tmp_path, capsys, **kwargs)
    assert rc2 == 1
    data2 = json.loads(out2)
    assert data2["error"] == "DUPLICATE_KNOWLEDGE"
    assert data2["classification"] == "DUPLICATE"

    rc3, _ = _run_cli(monkeypatch, tmp_path, ["memory", "status"], capsys)
    assert json.loads(_run_cli(monkeypatch, tmp_path, ["memory", "status"], capsys)[1])["note_counts"]["total"] == 1


def test_memory_add_with_force_writes_the_duplicate_anyway(monkeypatch, tmp_path, capsys):
    kwargs = dict(failure="stall on bulk transfer", root_cause="missing sync flop",
                  configuration="hs mode", error_pattern="timeout waiting ACK")
    rc1, _ = _add(monkeypatch, tmp_path, capsys, **kwargs)
    assert rc1 == 0
    rc2, out2 = _add(monkeypatch, tmp_path, capsys, force=True, **kwargs)
    assert rc2 == 0
    data2 = json.loads(out2)
    assert data2["ok"] is True
    assert data2["dedup_classification"] == "DUPLICATE"

    _, status_out = _run_cli(monkeypatch, tmp_path, ["memory", "status"], capsys)
    assert json.loads(status_out)["note_counts"]["total"] == 2


def test_memory_search_finds_a_written_note(monkeypatch, tmp_path, capsys):
    _add(monkeypatch, tmp_path, capsys, failure="clock domain crossing stall",
         root_cause="missing sync flop in phy")
    rc, out = _run_cli(monkeypatch, tmp_path, ["memory", "search", "clock domain"], capsys)
    assert rc == 0
    data = json.loads(out)
    assert len(data["results"]) == 1


def test_memory_show_reports_not_found_for_unknown_id(monkeypatch, tmp_path, capsys):
    rc, out = _run_cli(monkeypatch, tmp_path, ["memory", "show", "NOTE-NOPE"], capsys)
    assert rc == 1
    assert json.loads(out)["error"] == "NOT_FOUND"


# --- graph --------------------------------------------------------------------

def test_memory_graph_returns_the_root_node_with_no_links(monkeypatch, tmp_path, capsys):
    rc, out = _add(monkeypatch, tmp_path, capsys, root_cause="x")
    note_id = json.loads(out)["note_id"]
    rc2, out2 = _run_cli(monkeypatch, tmp_path, ["memory", "graph", note_id], capsys)
    assert rc2 == 0
    data = json.loads(out2)
    assert data["nodes"] == [note_id]
    assert data["edges"] == []


def test_memory_graph_follows_a_real_wikilink(monkeypatch, tmp_path, capsys):
    from dv_harness import memory_vault as mv
    provider = mv.get_active_provider(tmp_path, cfg={})
    a = provider.create({"memory_level": "engineering", "protocol": "USB", "status": "ACTIVE", "confidence": "HIGH"})
    b = provider.create(
        {"memory_level": "engineering", "protocol": "USB", "status": "ACTIVE", "confidence": "HIGH"},
        sections={"Related Knowledge": f"- [[{a['note_id']}]]"},
    )
    rc, out = _run_cli(monkeypatch, tmp_path, ["memory", "graph", b["note_id"]], capsys)
    assert rc == 0
    data = json.loads(out)
    assert a["note_id"] in data["nodes"]
    assert any(e["from"] == b["note_id"] and e["to"] == a["note_id"] for e in data["edges"])


# --- validate / doctor ---------------------------------------------------------

def test_memory_validate_ready_on_empty_vault(monkeypatch, tmp_path, capsys):
    rc, out = _run_cli(monkeypatch, tmp_path, ["memory", "validate"], capsys)
    assert rc == 0
    assert json.loads(out)["overall"] != "BLOCKED"


def test_memory_doctor_reports_partial_on_this_machine(monkeypatch, tmp_path, capsys):
    rc, out = _run_cli(monkeypatch, tmp_path, ["memory", "doctor"], capsys)
    assert rc == 0  # PARTIAL is a passing exit code (only BLOCKED exits 1)
    data = json.loads(out)
    assert data["overall"] in ("READY", "PARTIAL")
    assert "vault_path" in data


def test_memory_doctor_exits_nonzero_when_blocked(monkeypatch, tmp_path, capsys):
    from dv_harness import memory_vault as mv
    vault_path = mv.resolve_vault_path(tmp_path, cfg={})
    mv.bootstrap_vault(vault_path)
    eng_dir = vault_path / "06_Agent_Memory" / "Engineering"
    (eng_dir / "BROKEN.md").write_text("---\nid: BROKEN\n\nno closing delimiter", encoding="utf-8")

    rc, out = _run_cli(monkeypatch, tmp_path, ["memory", "doctor"], capsys)
    assert rc == 1
    assert json.loads(out)["overall"] == "BLOCKED"


# --- sync ----------------------------------------------------------------------

def test_memory_sync_reports_disabled_when_git_not_enabled(monkeypatch, tmp_path, capsys):
    rc, out = _run_cli(monkeypatch, tmp_path, ["memory", "sync"], capsys)
    assert rc == 0
    data = json.loads(out)
    assert data["git_enabled"] is False
    assert "disabled" in data["message"]


# --- promote --------------------------------------------------------------------

def test_memory_promote_reports_not_found_for_unknown_memory_id(monkeypatch, tmp_path, capsys):
    rc, out = _run_cli(monkeypatch, tmp_path, ["memory", "promote", "MEM-NOPE"], capsys)
    assert rc == 1
    data = json.loads(out)
    assert data["promoted"] is False
    assert data["error"] == "NOT_FOUND"


def test_memory_promote_succeeds_through_all_gates(monkeypatch, tmp_path, capsys):
    store = MemoryStore(tmp_path)
    rec = store.add("engineering", {
        "kind": "root_cause", "verified": True, "protocol": "USB", "root_cause": "phy sync missing",
        "status": "ACTIVE", "confirmation_count": 2,
        "verification": {"single_sim": "PASS", "regression": "PASS", "reaudit": "CLEAN"},
    })
    rc, out = _run_cli(monkeypatch, tmp_path, [
        "memory", "promote", rec["memory_id"],
        "--independent-sources", "3", "--evidence-refs-verified", "--multi-agent-consensus", "2",
    ], capsys)
    assert rc == 0
    data = json.loads(out)
    assert data["destination"] == "ORGANIZATIONAL_MEMORY"


def test_memory_promote_reports_gate_failure_reason_and_exits_nonzero(monkeypatch, tmp_path, capsys):
    store = MemoryStore(tmp_path)
    rec = store.add("engineering", {
        "kind": "root_cause", "verified": True, "protocol": "USB", "root_cause": "unverified claim",
        "status": "ACTIVE",
    })
    rc, out = _run_cli(monkeypatch, tmp_path, ["memory", "promote", rec["memory_id"]], capsys)
    assert rc == 1
    data = json.loads(out)
    assert data["promoted"] is False
    assert data["reason"] == "QUALITATIVE_GATE_FAILED"
