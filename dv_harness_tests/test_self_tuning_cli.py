import json
import sys
from pathlib import Path

import dv_harness.cli as cli_mod
from dv_harness.self_tuning import record_adjustment, apply_proposal, get_param


def _run_cli(monkeypatch, tmp_path, args, capsys):
    monkeypatch.setattr(sys, "argv", ["dv-harness", "--project-root", str(tmp_path)] + args)
    rc = cli_mod.main()
    out = capsys.readouterr().out
    return rc, out


def test_self_tune_status_shows_execution_count(monkeypatch, tmp_path, capsys):
    rc, out = _run_cli(monkeypatch, tmp_path, ["self-tune", "status"], capsys)
    assert rc == 0
    data = json.loads(out)
    assert "executions_since_last_review" in data


def test_self_tune_list_shows_pending_adjustment(monkeypatch, tmp_path, capsys):
    proposal = {"gate_id": "g", "change": {"param": "x", "from": 1, "to": 2},
                "rationale": "r", "confidence": "LOW", "risk_level": "LOW"}
    mem_id = record_adjustment(tmp_path, proposal, status="PENDING")

    rc, out = _run_cli(monkeypatch, tmp_path, ["self-tune", "list", "--pending"], capsys)
    assert rc == 0
    data = json.loads(out)
    ids = [r["memory_id"] for r in data["records"]]
    assert mem_id in ids


def test_self_tune_approve_applies_a_pending_adjustment(monkeypatch, tmp_path, capsys):
    proposal = {"gate_id": "g", "change": {"param": "x", "from": 1, "to": 2},
                "rationale": "r", "confidence": "LOW", "risk_level": "LOW"}
    mem_id = record_adjustment(tmp_path, proposal, status="PENDING")

    rc, out = _run_cli(monkeypatch, tmp_path, ["self-tune", "approve", mem_id], capsys)
    assert rc == 0
    assert get_param(tmp_path, "g", "x", None) == 2
