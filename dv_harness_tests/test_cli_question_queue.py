"""Tests for the `dv-harness question-queue ...` CLI subcommand group (spec
Part B). Runs `dv_harness.cli.main()` in-process against a fresh
--project-root tmp_path, following the same monkeypatched-sys.argv pattern
already established by dv_harness_tests/test_cli_memory_commands.py.
"""
from __future__ import annotations

import json
import sys

import pytest

import dv_harness.cli as cli_mod


def _run_cli(monkeypatch, tmp_path, args, capsys):
    monkeypatch.setattr(sys, "argv", ["dv-harness", "--project-root", str(tmp_path)] + args)
    try:
        rc = cli_mod.main()
    except SystemExit as e:
        rc = e.code
    out = capsys.readouterr().out
    return (rc if rc is not None else 0), out


def _add(monkeypatch, tmp_path, capsys, *, domain="dut", question="q?", context_path="p",
          options=("Option A", "Option B"), recommendation="Option A", assumption="n/a",
          extra=None):
    args = ["question-queue", "add", "--domain", domain, "--question", question,
            "--context-path", context_path, "--recommendation", recommendation,
            "--assumption-if-unanswered", assumption]
    for o in options:
        args += ["--option", o]
    if extra:
        args += extra
    return _run_cli(monkeypatch, tmp_path, args, capsys)


def test_add_tier3_question_via_cli(monkeypatch, tmp_path, capsys):
    rc, out = _add(monkeypatch, tmp_path, capsys, extra=["--affects-pass-fail-verdict"])
    assert rc == 0
    data = json.loads(out)
    assert data["tier"] == 3
    assert data["blocking"] is True
    assert data["status"] == "OPEN"
    assert data["owner"] == "designer"


def test_add_rejects_fewer_than_two_options(monkeypatch, tmp_path, capsys):
    args = ["question-queue", "add", "--domain", "vip", "--question", "q?",
            "--context-path", "p", "--option", "only one", "--recommendation", "only one",
            "--assumption-if-unanswered", "a"]
    rc, out = _run_cli(monkeypatch, tmp_path, args, capsys)
    assert rc != 0
    assert json.loads(out)["error"] == "AT_LEAST_TWO_OPTIONS_REQUIRED"


def test_list_filters_by_status_and_domain(monkeypatch, tmp_path, capsys):
    _add(monkeypatch, tmp_path, capsys, domain="vip", context_path="p1",
         extra=["--affects-spec-intent"])
    _add(monkeypatch, tmp_path, capsys, domain="dut", context_path="p2")  # tier 2, ASSUMED

    rc, out = _run_cli(monkeypatch, tmp_path, ["question-queue", "list", "--status", "OPEN"], capsys)
    assert rc == 0
    results = json.loads(out)
    assert len(results) == 1
    assert results[0]["domain"] == "vip"

    rc2, out2 = _run_cli(monkeypatch, tmp_path, ["question-queue", "list", "--domain", "dut"], capsys)
    results2 = json.loads(out2)
    assert len(results2) == 1
    assert results2[0]["status"] == "ASSUMED"


def test_answer_then_repeat_add_self_resolves_via_cli(monkeypatch, tmp_path, capsys):
    rc, out = _add(monkeypatch, tmp_path, capsys, domain="dut", question="W1C register?",
                    context_path="dut.regs.R0", extra=["--affects-pass-fail-verdict"])
    qid = json.loads(out)["id"]
    assert json.loads(out)["status"] == "OPEN"

    rc2, out2 = _run_cli(monkeypatch, tmp_path, ["question-queue", "answer", qid,
                                                    "--answer", "Yes, W1C.", "--basis", "RTL line 42",
                                                    "--decided-by", "designer@example.com"], capsys)
    assert rc2 == 0
    assert json.loads(out2)["status"] == "ANSWERED"

    rc3, out3 = _add(monkeypatch, tmp_path, capsys, domain="dut", question="W1C register?",
                       context_path="dut.regs.R0", extra=["--affects-pass-fail-verdict"])
    repeated = json.loads(out3)
    assert repeated["id"] == qid
    assert repeated["tier"] == 1
    assert repeated["status"] == "SELF_RESOLVED"
    assert repeated["answer"] == "Yes, W1C."

    rc4, out4 = _run_cli(monkeypatch, tmp_path, ["question-queue", "status"], capsys)
    metrics = json.loads(out4)
    assert metrics["repeat_question_rate_percent"] == 0.0


def test_answer_unknown_question_id_fails_cleanly(monkeypatch, tmp_path, capsys):
    rc, out = _run_cli(monkeypatch, tmp_path, ["question-queue", "answer", "Q-DUT-DEADBEEF",
                                                  "--answer", "x", "--basis", "y"], capsys)
    assert rc != 0
    assert json.loads(out)["ok"] is False


def test_digest_manual_via_cli(monkeypatch, tmp_path, capsys):
    _add(monkeypatch, tmp_path, capsys, domain="env", context_path="p1", extra=["--affects-read-only-file-change"])
    rc, out = _run_cli(monkeypatch, tmp_path, ["question-queue", "digest", "--trigger", "manual"], capsys)
    assert rc == 0
    digest = json.loads(out)
    assert digest["emitted"] is True
    assert "DV-owner" in digest["by_owner"]


def test_F3a_tier2_assumption_does_not_suppress_a_later_tier3_via_cli(monkeypatch, tmp_path, capsys):
    # Review defect F3-a, driven entirely through the shipped CLI: the same
    # question_key asked first in a low-risk framing, then with every
    # Tier-3 hard trigger set.
    common = dict(domain="dut", question="Is a TX_ERR drop legal per spec?", context_path="dut.regs.TX_ERR",
                  assumption="Assume legal drop per spec.")
    rc1, out1 = _add(monkeypatch, tmp_path, capsys, **common)
    first = json.loads(out1)
    assert first["tier"] == 2 and first["status"] == "ASSUMED"

    rc2, out2 = _add(monkeypatch, tmp_path, capsys, **common,
                      extra=["--affects-pass-fail-verdict", "--affects-spec-intent",
                             "--affects-read-only-file-change", "--blast-radius", "unbounded"])
    second = json.loads(out2)
    assert second["id"] == first["id"]  # same question_key
    assert second["tier"] == 3
    assert second["blocking"] is True
    assert second["status"] == "OPEN"
    assert second["answer"] is None

    # It really escalates: it shows up in the digest a human reads.
    rc3, out3 = _run_cli(monkeypatch, tmp_path, ["question-queue", "digest", "--trigger", "manual"], capsys)
    assert second["id"] in [q["id"] for q in json.loads(out3)["questions"]]


def test_F3b_manifest_flags_cannot_resolve_a_hard_trigger_question_via_cli(monkeypatch, tmp_path, capsys):
    # Review defect F3-b at the CLI boundary: --resolvable-from-manifest
    # with an unrelated value must not resolve a cannot-assume question.
    rc, out = _add(monkeypatch, tmp_path, capsys, domain="dut",
                    question="Is a TX_ERR drop legal per spec, or a real DUT failure?",
                    context_path="dut.regs.TX_ERR",
                    extra=["--affects-pass-fail-verdict", "--affects-spec-intent",
                           "--blast-radius", "unbounded",
                           "--resolvable-from-manifest", "--manifest-value", "offset=0x40,width=32,access=RW"])
    assert rc == 0
    data = json.loads(out)
    assert data["tier"] == 3
    assert data["blocking"] is True
    assert data["status"] == "OPEN"
    assert data["answer"] is None


def test_revoke_via_cli_then_reask_escalates(monkeypatch, tmp_path, capsys):
    rc, out = _add(monkeypatch, tmp_path, capsys, domain="env", question="Is monitor4 passive?",
                    context_path="env.topology.monitor4", assumption="Treat monitor4 as passive-only.")
    first = json.loads(out)
    assert first["tier"] == 2
    key = first["question_key"]

    rc2, out2 = _run_cli(monkeypatch, tmp_path, ["question-queue", "revoke", key,
                                                    "--reason", "topology print says active",
                                                    "--revoked-by", "dv_owner@example.com"], capsys)
    assert rc2 == 0
    revocation = json.loads(out2)
    assert revocation["question_key"] == key
    assert revocation["reason"] == "topology print says active"

    # Re-asking with a real Tier-3 trigger now escalates rather than being
    # shortcut by the withdrawn assumption.
    rc3, out3 = _add(monkeypatch, tmp_path, capsys, domain="env", question="Is monitor4 passive?",
                      context_path="env.topology.monitor4", assumption="Treat monitor4 as passive-only.",
                      extra=["--affects-pass-fail-verdict"])
    assert json.loads(out3)["tier"] == 3
    assert json.loads(out3)["status"] == "OPEN"


def test_revoke_unknown_key_fails_cleanly_via_cli(monkeypatch, tmp_path, capsys):
    rc, out = _run_cli(monkeypatch, tmp_path, ["question-queue", "revoke", "no-such-key",
                                                  "--reason", "x"], capsys)
    assert rc != 0
    assert json.loads(out)["ok"] is False


def test_status_reports_four_metrics(monkeypatch, tmp_path, capsys):
    _add(monkeypatch, tmp_path, capsys, domain="vip", context_path="p1", extra=["--affects-spec-intent"])
    rc, out = _run_cli(monkeypatch, tmp_path, ["question-queue", "status"], capsys)
    assert rc == 0
    metrics = json.loads(out)
    for key in ("self_resolve_rate_percent", "blocking_questions_per_week",
                "repeat_question_rate_percent", "assumption_overturned_rate_percent"):
        assert key in metrics
