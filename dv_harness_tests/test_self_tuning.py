import json
import tempfile
import shutil
from pathlib import Path

from dv_harness.self_tuning import (
    get_param, set_param, read_overrides, propose_add_override,
    propose_remove_override, PROTECTED_REMOVALS, read_execution_state,
    increment_execution_counter, reset_execution_counter,
    append_gate_history, read_gate_history_since, gate_history_length,
)


def _tmp_root():
    return Path(tempfile.mkdtemp())


def test_get_param_returns_default_when_file_absent():
    root = _tmp_root()
    try:
        assert get_param(root, "fake_gate", "threshold", 5) == 5
    finally:
        shutil.rmtree(root)


def test_set_param_then_get_param_round_trips():
    root = _tmp_root()
    try:
        set_param(root, "fake_gate", "threshold", 42)
        assert get_param(root, "fake_gate", "threshold", 5) == 42
        assert get_param(root, "fake_gate", "other", "d") == "d"
    finally:
        shutil.rmtree(root)


def test_get_param_returns_default_on_malformed_json():
    root = _tmp_root()
    try:
        p = root / ".dv-harness" / "self_tuning"
        p.mkdir(parents=True)
        (p / "parameters.json").write_text("{not json", encoding="utf-8")
        assert get_param(root, "fake_gate", "threshold", 5) == 5
    finally:
        shutil.rmtree(root)


def test_read_overrides_empty_when_absent():
    root = _tmp_root()
    try:
        assert read_overrides(root) == {}
    finally:
        shutil.rmtree(root)


def test_propose_add_override_writes_and_round_trips():
    root = _tmp_root()
    try:
        propose_add_override(root, "IMPLEMENT", "fake_gate")
        overrides = read_overrides(root)
        assert overrides["IMPLEMENT"]["add"] == ["fake_gate"]
    finally:
        shutil.rmtree(root)


def test_propose_remove_override_blocks_protected_pair():
    root = _tmp_root()
    try:
        protected_stage, protected_gate = next(iter(PROTECTED_REMOVALS))
        ok = propose_remove_override(root, protected_stage, protected_gate)
        assert ok is False
        overrides = read_overrides(root)
        assert protected_gate not in overrides.get(protected_stage, {}).get("remove", [])
    finally:
        shutil.rmtree(root)


def test_propose_remove_override_allows_unprotected_pair():
    root = _tmp_root()
    try:
        ok = propose_remove_override(root, "COMMAND_PATTERN", "some_unprotected_gate")
        assert ok is True
        overrides = read_overrides(root)
        assert overrides["COMMAND_PATTERN"]["remove"] == ["some_unprotected_gate"]
    finally:
        shutil.rmtree(root)


def test_execution_counter_increments_and_resets():
    root = _tmp_root()
    try:
        assert read_execution_state(root)["executions_since_last_review"] == 0
        assert increment_execution_counter(root) == 1
        assert increment_execution_counter(root) == 2
        reset_execution_counter(root)
        assert read_execution_state(root)["executions_since_last_review"] == 0
    finally:
        shutil.rmtree(root)


def test_gate_history_append_and_read_since():
    root = _tmp_root()
    try:
        append_gate_history(root, "gate_a", "IMPLEMENT", True, "PASS", 1.0)
        append_gate_history(root, "gate_b", "IMPLEMENT", False, "GATE_FAIL", 2.0)
        assert gate_history_length(root) == 2
        entries = read_gate_history_since(root, 1)
        assert len(entries) == 1
        assert entries[0]["gate_id"] == "gate_b"
    finally:
        shutil.rmtree(root)
