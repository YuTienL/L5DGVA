"""dv_harness_tests/test_git_governance.py -- gh CLI + PR-only governance
gate (2026-09-03 task): unit tests for the pure decision logic in
dv_harness/git_governance.py.

Mirrors dv_harness_tests/test_remote_relay.py's own established discipline
for this exact class of problem (an AI-agent-environment guard): test the
pure function against constructed env dicts / real-shaped git hook input,
never by actually running a live git push/merge against a real branch.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "remote"))

from dv_harness import git_governance as gg
import remote_relay  # type: ignore


# --- Reuse, not duplication: AI_AGENT_ENV_MARKERS must be the SAME object
# remote_relay.py defines, so the two guards can never silently drift apart
# (the whole point of importing it rather than copy-pasting the tuple). ---

def test_ai_agent_env_markers_is_reused_from_remote_relay_not_duplicated():
    assert gg.AI_AGENT_ENV_MARKERS is remote_relay.AI_AGENT_ENV_MARKERS
    assert "CLAUDECODE" in gg.AI_AGENT_ENV_MARKERS
    assert "ANTHROPIC_API_KEY" in gg.AI_AGENT_ENV_MARKERS


# --- detect_ai_agent_markers -------------------------------------------

def test_detect_ai_agent_markers_empty_env_returns_empty_list():
    assert gg.detect_ai_agent_markers({}) == []


def test_detect_ai_agent_markers_detects_claudecode():
    assert gg.detect_ai_agent_markers({"CLAUDECODE": "1"}) == ["CLAUDECODE"]


def test_detect_ai_agent_markers_detects_anthropic_api_key():
    assert gg.detect_ai_agent_markers({"ANTHROPIC_API_KEY": "sk-fake"}) == ["ANTHROPIC_API_KEY"]


def test_detect_ai_agent_markers_ignores_empty_string_value():
    # A marker present but set to "" must not count as "present" -- same
    # falsy-value convention remote_relay.running_inside_ai_agent() uses
    # (os.environ.get(marker) is used as a truthiness test there too).
    assert gg.detect_ai_agent_markers({"CLAUDECODE": ""}) == []


def test_detect_ai_agent_markers_finds_multiple_in_declared_order():
    env = {"ANTHROPIC_API_KEY": "sk-fake", "CLAUDECODE": "1"}
    found = gg.detect_ai_agent_markers(env)
    assert set(found) == {"CLAUDECODE", "ANTHROPIC_API_KEY"}
    # declared order == AI_AGENT_ENV_MARKERS order, not dict insertion order
    assert found == [m for m in gg.AI_AGENT_ENV_MARKERS if m in found]


def test_detect_ai_agent_markers_no_override_variable_exists():
    # Deliberate design difference from remote_relay.py's Layer 2: this
    # gate has NO opt-out. Setting the relay's own override var must have
    # zero effect here.
    env = {"CLAUDECODE": "1", "DV_HARNESS_RELAY_AUTORECONNECT_OK": "1"}
    assert gg.detect_ai_agent_markers(env) == ["CLAUDECODE"]


# --- branch_from_ref / is_protected_branch ------------------------------

def test_branch_from_ref_extracts_simple_branch_name():
    assert gg.branch_from_ref("refs/heads/main") == "main"
    assert gg.branch_from_ref("refs/heads/master") == "master"


def test_branch_from_ref_extracts_nested_branch_name():
    assert gg.branch_from_ref("refs/heads/feature/foo") == "feature/foo"


def test_branch_from_ref_returns_none_for_non_branch_ref():
    assert gg.branch_from_ref("refs/tags/v1.0") is None
    assert gg.branch_from_ref("refs/for/main") is None


def test_is_protected_branch_true_for_main_and_master():
    assert gg.is_protected_branch("main") is True
    assert gg.is_protected_branch("master") is True


def test_is_protected_branch_false_for_feature_branch_or_none():
    assert gg.is_protected_branch("feature/x") is False
    assert gg.is_protected_branch(None) is False


# --- parse_pre_push_refspecs (real githooks(5) stdin shape) --------------

def test_parse_pre_push_refspecs_real_single_line_shape():
    stdin = "refs/heads/feature/x abc123 refs/heads/feature/x def456\n"
    specs = gg.parse_pre_push_refspecs(stdin)
    assert len(specs) == 1
    s = specs[0]
    assert s.local_ref == "refs/heads/feature/x"
    assert s.local_sha == "abc123"
    assert s.remote_ref == "refs/heads/feature/x"
    assert s.remote_sha == "def456"
    assert s.branch == "feature/x"
    assert s.protected is False


def test_parse_pre_push_refspecs_flags_protected_branch():
    stdin = "refs/heads/main abc123 refs/heads/main def456\n"
    specs = gg.parse_pre_push_refspecs(stdin)
    assert specs[0].protected is True
    assert specs[0].branch == "main"


def test_parse_pre_push_refspecs_multiple_lines():
    stdin = (
        "refs/heads/feature/a a1 refs/heads/feature/a a2\n"
        "refs/heads/master b1 refs/heads/master b2\n"
    )
    specs = gg.parse_pre_push_refspecs(stdin)
    assert len(specs) == 2
    assert specs[0].protected is False
    assert specs[1].protected is True


def test_parse_pre_push_refspecs_skips_blank_lines():
    stdin = "\nrefs/heads/main a1 refs/heads/main a2\n\n"
    specs = gg.parse_pre_push_refspecs(stdin)
    assert len(specs) == 1


def test_parse_pre_push_refspecs_skips_malformed_lines_without_crashing():
    stdin = "this is not a valid refspec line\nrefs/heads/main a1 refs/heads/main a2\n"
    specs = gg.parse_pre_push_refspecs(stdin)
    assert len(specs) == 1
    assert specs[0].branch == "main"


def test_parse_pre_push_refspecs_empty_stdin_returns_empty_list():
    assert gg.parse_pre_push_refspecs("") == []


# --- evaluate_pre_push: the real decision --------------------------------

def test_pre_push_allowed_when_no_protected_branch_pushed_even_with_agent_marker():
    stdin = "refs/heads/feature/x a1 refs/heads/feature/x a2\n"
    d = gg.evaluate_pre_push(stdin, {"CLAUDECODE": "1"})
    assert d.allowed is True
    assert d.hook == "pre-push"
    assert d.detected_markers == []
    assert d.branch is None


def test_pre_push_allowed_when_protected_branch_pushed_by_a_human():
    stdin = "refs/heads/main a1 refs/heads/main a2\n"
    d = gg.evaluate_pre_push(stdin, {})
    assert d.allowed is True
    assert d.branch == "main"
    assert d.detected_markers == []


def test_pre_push_blocked_when_agent_pushes_main_directly():
    stdin = "refs/heads/main a1 refs/heads/main a2\n"
    d = gg.evaluate_pre_push(stdin, {"CLAUDECODE": "1"})
    assert d.allowed is False
    assert d.branch == "main"
    assert d.detected_markers == ["CLAUDECODE"]
    assert "BLOCKED" in d.reason
    assert "gh pr create" in d.reason


def test_pre_push_blocked_when_agent_pushes_master_directly():
    stdin = "refs/heads/master a1 refs/heads/master a2\n"
    d = gg.evaluate_pre_push(stdin, {"ANTHROPIC_API_KEY": "sk-fake"})
    assert d.allowed is False
    assert d.branch == "master"


def test_pre_push_allowed_when_agent_pushes_a_feature_branch():
    # This IS the sanctioned agent workflow -- branch/commit/PR.
    stdin = "refs/heads/feature/my-change a1 refs/heads/feature/my-change a2\n"
    d = gg.evaluate_pre_push(stdin, {"CLAUDECODE": "1"})
    assert d.allowed is True


def test_pre_push_decision_carries_refspec_evidence():
    stdin = "refs/heads/main a1 refs/heads/main a2\n"
    d = gg.evaluate_pre_push(stdin, {"CLAUDECODE": "1"})
    assert d.refspecs == [{
        "local_ref": "refs/heads/main", "local_sha": "a1",
        "remote_ref": "refs/heads/main", "remote_sha": "a2",
        "branch": "main", "protected": True,
    }]


def test_pre_push_to_dict_is_json_serializable_shape():
    import json
    stdin = "refs/heads/main a1 refs/heads/main a2\n"
    d = gg.evaluate_pre_push(stdin, {"CLAUDECODE": "1"})
    encoded = json.dumps(d.to_dict())
    assert "BLOCKED" in encoded


# --- evaluate_pre_merge_commit -------------------------------------------

def test_pre_merge_commit_allowed_on_a_feature_branch_with_agent_marker():
    d = gg.evaluate_pre_merge_commit("feature/x", {"CLAUDECODE": "1"})
    assert d.allowed is True
    assert d.hook == "pre-merge-commit"


def test_pre_merge_commit_allowed_on_main_by_a_human():
    d = gg.evaluate_pre_merge_commit("main", {})
    assert d.allowed is True
    assert d.branch == "main"


def test_pre_merge_commit_blocked_on_main_by_an_agent():
    d = gg.evaluate_pre_merge_commit("main", {"CLAUDECODE": "1"})
    assert d.allowed is False
    assert d.branch == "main"
    assert d.detected_markers == ["CLAUDECODE"]
    assert "gh pr create" in d.reason


def test_pre_merge_commit_blocked_on_master_by_an_agent():
    d = gg.evaluate_pre_merge_commit("master", {"CLAUDE_CODE_SESSION_ID": "s-1"})
    assert d.allowed is False
    assert d.branch == "master"


def test_pre_merge_commit_handles_none_branch_without_crashing():
    d = gg.evaluate_pre_merge_commit(None, {"CLAUDECODE": "1"})
    assert d.allowed is True  # None is not a protected branch
