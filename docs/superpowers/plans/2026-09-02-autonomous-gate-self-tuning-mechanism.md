# Autonomous Gate Self-Tuning (Mechanism Only) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the autonomous gate self-tuning mechanism (tunable-parameter layer, stage-gate membership overlay, retrospective review cycle, confidence/risk-gated apply-vs-defer, audit trail, revert) using only synthetic/fake gate_ids in every test — zero real existing gate script is refactored or behaviorally changed by this plan.

**Architecture:** A new `dv_harness/self_tuning.py` module owns two JSON files under `.dv-harness/self_tuning/` (`parameters.json`, `stage_gate_overrides.json`) plus an append-only `gate_history.jsonl` and a `state.json` execution counter. `dv_harness/gates.py` gains `effective_stage_gates()` (overlay applied over the hardcoded `STAGE_GATES` dict, with a hardcoded protected-removal list enforced inside it) and gate-history logging wired into the existing `run_gate()`. A new gate script, `tools/verification_flow/self_tuning_proposal_gate.py`, mechanically strips any LLM-proposed adjustment that touches the protected list. `dv_harness/engine.py` gains an inline review-cycle trigger (same call-shape as the existing `_promote_verified_fix_knowledge`) that assembles evidence, dispatches the existing `ClaudeCLIAdapter`, validates the response through the proposal gate, classifies each surviving proposal as auto-apply or defer-to-human, and persists every outcome to Engineering Memory. New `dv-harness self-tune status/list/approve/reject/revert` CLI subcommands complete the human-facing surface.

**Tech Stack:** Python 3.7+ compatible (this codebase runs on a remote Python 3.7 deployment — no `dict|dict` merges, no `Path.unlink(missing_ok=)`, no `shutil.copytree(dirs_exist_ok=)`), pytest, existing `dv_harness` conventions (`storage._atomic_replace`, `gates.GateResult`/`run_gate`/`extract_evidence_blocks`, `adapters.base.AgentResult`, `memory_router.route_and_store`).

**Spec:** `docs/superpowers/specs/2026-09-02-autonomous-gate-self-tuning-design.md` — this plan implements ONLY that spec's "Rollout plan" step 1 ("Build the mechanism ... with zero gates refactored yet"). Steps 2 (real safety-list audit) and 3 (refactor a first batch of real gates) are explicitly out of scope for this plan.

## Global Constraints

- Self-tuning may only ever write to `.dv-harness/self_tuning/parameters.json` and `.dv-harness/self_tuning/stage_gate_overrides.json` (plus its own `gate_history.jsonl`/`state.json`) — never any `.py` source file, never `gates.py`'s `STAGE_GATES` dict literal, never `engine.py`'s control flow.
- Every JSON write in this feature uses `dv_harness/storage.py`'s existing `_atomic_replace(tmp, dest)` helper (`tempfile.mkstemp` + `os.fdopen` + `_atomic_replace`), matching `control_plane.py`'s established pattern — never a bare `path.write_text()` for these files.
- Protected-removal list (hardcoded Python constant, never JSON-configurable): `rtl_write_scope_guard_gate`/`IMPLEMENT`, `fix_risk_approval_gate`/`RE_AUDIT`, `manual_lookup_before_edit_gate`/`IMPLEMENT`, `protocol_isolation_gate`/`IMPLEMENT`, plus every gate_id currently listed under `STAGE_GATES["PROMOTION_READINESS"]` and `STAGE_GATES["SIGNOFF"]` (computed dynamically from the live dict, not a separately-maintained copy that can drift).
- No adjustment record is ever pushed to the shared cross-user Knowledge Center — `route_and_store()` is called WITHOUT triggering a shared push for `kind="self_tuning_adjustment"` records (this kind is not `verified_fix`/`debug_lesson`/etc., so `route_memory()` must route it to a project-local destination, not `ENGINEERING_MEMORY`'s shareable path — see Task 4).
- Every exception anywhere in the review-cycle path must be caught at the top of the inline call site and never propagate — a self-tuning failure must never break or block the real stage result it's piggybacking on (same defensive discipline as `memory_router._maybe_share`).
- Python 3.7 compatibility: no `X | Y` dict merges, no `Path.unlink(missing_ok=True)` (use `try/except FileNotFoundError`), no `shutil.copytree(dirs_exist_ok=True)`.

---

### Task 1: `dv_harness/self_tuning.py` — data layer

**Files:**
- Create: `dv_harness/self_tuning.py`
- Test: `dv_harness_tests/test_self_tuning.py`

**Interfaces:**
- Consumes: `dv_harness.storage._atomic_replace(tmp: str, dest: Path) -> None` (existing).
- Produces (used by later tasks):
  - `SELF_TUNING_DIR = ".dv-harness/self_tuning"` (module constant)
  - `get_param(root: Path, gate_id: str, name: str, default) -> Any`
  - `set_param(root: Path, gate_id: str, name: str, value) -> None`
  - `read_overrides(root: Path) -> dict` — shape `{"<STAGE>": {"add": [...], "remove": [...]}}`, `{}` if file absent/malformed
  - `PROTECTED_REMOVALS: set` — a module-level set of `(stage, gate_id)` tuples, computed once at import time by reading `dv_harness.gates.STAGE_GATES["PROMOTION_READINESS"]`/`["SIGNOFF"]` plus the 4 hardcoded pairs from Global Constraints (a function `_compute_protected_removals() -> set` so tests can call it directly without import-time side effects being hard to reset)
  - `propose_remove_override(root: Path, stage: str, gate_id: str) -> bool` — returns `False` (no-op, does NOT write) if `(stage, gate_id)` is in `PROTECTED_REMOVALS`; otherwise appends to that stage's `"remove"` list and writes, returns `True`
  - `propose_add_override(root: Path, stage: str, gate_id: str) -> None` — appends to that stage's `"add"` list, writes
  - `read_execution_state(root: Path) -> dict` — shape `{"executions_since_last_review": int}`, defaults to `{"executions_since_last_review": 0}` if absent
  - `increment_execution_counter(root: Path) -> int` — reads, increments, writes, returns new value
  - `reset_execution_counter(root: Path) -> None` — writes `{"executions_since_last_review": 0}`
  - `append_gate_history(root: Path, gate_id: str, stage: str, ok: bool, reason: str, timestamp: float) -> None` — appends one JSON line to `gate_history.jsonl`
  - `read_gate_history_since(root: Path, since_index: int) -> list` — returns history entries from `since_index` onward (list of dicts); also `gate_history_length(root: Path) -> int` so a caller can record "read up to here" as the next cycle's start point

- [ ] **Step 1: Write the failing tests**

```python
# dv_harness_tests/test_self_tuning.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest dv_harness_tests/test_self_tuning.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'dv_harness.self_tuning'`

- [ ] **Step 3: Write the implementation**

```python
# dv_harness/self_tuning.py
from __future__ import annotations
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List

from .storage import _atomic_replace

SELF_TUNING_DIR = ".dv-harness/self_tuning"


def _dir(root: Path) -> Path:
    d = root / ".dv-harness" / "self_tuning"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _params_path(root: Path) -> Path:
    return _dir(root) / "parameters.json"


def _overrides_path(root: Path) -> Path:
    return _dir(root) / "stage_gate_overrides.json"


def _state_path(root: Path) -> Path:
    return _dir(root) / "state.json"


def _history_path(root: Path) -> Path:
    return _dir(root) / "gate_history.jsonl"


def _read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json_atomic(path: Path, data) -> None:
    fd, tmp = tempfile.mkstemp(prefix=path.stem + ".", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        _atomic_replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def get_param(root: Path, gate_id: str, name: str, default: Any) -> Any:
    data = _read_json(_params_path(root), {})
    if not isinstance(data, dict):
        return default
    return data.get(gate_id, {}).get(name, default)


def set_param(root: Path, gate_id: str, name: str, value: Any) -> None:
    data = _read_json(_params_path(root), {})
    if not isinstance(data, dict):
        data = {}
    data.setdefault(gate_id, {})[name] = value
    _write_json_atomic(_params_path(root), data)


def read_overrides(root: Path) -> Dict[str, Any]:
    data = _read_json(_overrides_path(root), {})
    return data if isinstance(data, dict) else {}


def _compute_protected_removals() -> set:
    from . import gates as _gates
    protected = {
        ("IMPLEMENT", "rtl_write_scope_guard_gate"),
        ("RE_AUDIT", "fix_risk_approval_gate"),
        ("IMPLEMENT", "manual_lookup_before_edit_gate"),
        ("IMPLEMENT", "protocol_isolation_gate"),
    }
    for stage in ("PROMOTION_READINESS", "SIGNOFF"):
        for entry in _gates.STAGE_GATES.get(stage, []):
            gate_id = entry[0]
            protected.add((stage, gate_id))
    return protected


PROTECTED_REMOVALS = _compute_protected_removals()


def propose_add_override(root: Path, stage: str, gate_id: str) -> None:
    overrides = read_overrides(root)
    stage_entry = overrides.setdefault(stage, {"add": [], "remove": []})
    stage_entry.setdefault("add", [])
    if gate_id not in stage_entry["add"]:
        stage_entry["add"].append(gate_id)
    _write_json_atomic(_overrides_path(root), overrides)


def propose_remove_override(root: Path, stage: str, gate_id: str) -> bool:
    if (stage, gate_id) in PROTECTED_REMOVALS:
        return False
    overrides = read_overrides(root)
    stage_entry = overrides.setdefault(stage, {"add": [], "remove": []})
    stage_entry.setdefault("remove", [])
    if gate_id not in stage_entry["remove"]:
        stage_entry["remove"].append(gate_id)
    _write_json_atomic(_overrides_path(root), overrides)
    return True


def read_execution_state(root: Path) -> Dict[str, Any]:
    return _read_json(_state_path(root), {"executions_since_last_review": 0})


def increment_execution_counter(root: Path) -> int:
    state = read_execution_state(root)
    state["executions_since_last_review"] = state.get("executions_since_last_review", 0) + 1
    _write_json_atomic(_state_path(root), state)
    return state["executions_since_last_review"]


def reset_execution_counter(root: Path) -> None:
    _write_json_atomic(_state_path(root), {"executions_since_last_review": 0})


def append_gate_history(root: Path, gate_id: str, stage: str, ok: bool, reason: str, timestamp: float) -> None:
    entry = {"gate_id": gate_id, "stage": stage, "ok": ok, "reason": reason, "timestamp": timestamp}
    with open(_history_path(root), "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def gate_history_length(root: Path) -> int:
    p = _history_path(root)
    if not p.exists():
        return 0
    with open(p, "r", encoding="utf-8") as f:
        return sum(1 for _ in f)


def read_gate_history_since(root: Path, since_index: int) -> List[Dict[str, Any]]:
    p = _history_path(root)
    if not p.exists():
        return []
    out = []
    with open(p, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i < since_index:
                continue
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest dv_harness_tests/test_self_tuning.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add dv_harness/self_tuning.py dv_harness_tests/test_self_tuning.py
git commit -m "feat: add self_tuning.py data layer (parameters, overrides, execution counter, gate history)"
```

---

### Task 2: Wire `effective_stage_gates()` and gate-history logging into `gates.py`

**Files:**
- Modify: `dv_harness/gates.py` (read `STAGE_GATES` dict definition and `run_gate()` fully first — do not assume line numbers, the file has been edited multiple times this session)
- Test: `dv_harness_tests/test_self_tuning.py` (add to the file from Task 1)

**Interfaces:**
- Consumes: `dv_harness.self_tuning.read_overrides`, `PROTECTED_REMOVALS`, `append_gate_history` (Task 1).
- Produces: `dv_harness.gates.effective_stage_gates(stage: str, root: Path) -> list` (same element shape as `STAGE_GATES[stage]` — list of `(gate_id, script_name, cli_flag)` tuples).

- [ ] **Step 1: Write the failing tests**

Append to `dv_harness_tests/test_self_tuning.py`:

```python
from dv_harness.gates import effective_stage_gates, STAGE_GATES
from dv_harness.self_tuning import propose_add_override, propose_remove_override


def test_effective_stage_gates_matches_baseline_when_no_overrides():
    root = _tmp_root()
    try:
        assert effective_stage_gates("COMMAND_PATTERN", root) == STAGE_GATES["COMMAND_PATTERN"]
    finally:
        shutil.rmtree(root)


def test_effective_stage_gates_applies_add_override():
    root = _tmp_root()
    try:
        propose_add_override(root, "COMMAND_PATTERN", "fake_extra_gate")
        result = effective_stage_gates("COMMAND_PATTERN", root)
        ids = [g[0] for g in result]
        assert "fake_extra_gate" in ids
    finally:
        shutil.rmtree(root)


def test_effective_stage_gates_ignores_protected_removal():
    root = _tmp_root()
    try:
        # fix_risk_approval_gate/RE_AUDIT is protected -- direct JSON write
        # (bypassing propose_remove_override's own check) to prove
        # effective_stage_gates() enforces this independently, not only
        # the proposer function.
        from dv_harness.self_tuning import _overrides_path, _write_json_atomic
        _write_json_atomic(_overrides_path(root), {
            "RE_AUDIT": {"add": [], "remove": ["fix_risk_approval_gate"]}
        })
        result = effective_stage_gates("RE_AUDIT", root)
        ids = [g[0] for g in result]
        assert "fix_risk_approval_gate" in ids
    finally:
        shutil.rmtree(root)


def test_effective_stage_gates_applies_unprotected_removal():
    root = _tmp_root()
    try:
        propose_remove_override(root, "COMMAND_PATTERN", "command_migration_integrity_gate")
        result = effective_stage_gates("COMMAND_PATTERN", root)
        ids = [g[0] for g in result]
        assert "command_migration_integrity_gate" not in ids
    finally:
        shutil.rmtree(root)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest dv_harness_tests/test_self_tuning.py -v -k effective_stage_gates`
Expected: FAIL with `ImportError: cannot import name 'effective_stage_gates'`

- [ ] **Step 3: Implement**

Add to `dv_harness/gates.py`, after the `STAGE_GATES` dict definition (find the closing `}` of `STAGE_GATES = { ... }` and add immediately after it):

```python
def effective_stage_gates(stage: str, root: "Path") -> list:
    """STAGE_GATES[stage] with the self-tuning overlay (.dv-harness/
    self_tuning/stage_gate_overrides.json) applied. Protected (stage,
    gate_id) pairs (dv_harness.self_tuning.PROTECTED_REMOVALS) can never be
    removed here regardless of what the overlay file says -- enforced in
    this function itself, not merely by the proposer that writes the
    overlay, so a hand-edited or otherwise-produced overrides file can
    never bypass the safety invariant."""
    from . import self_tuning
    baseline = list(STAGE_GATES.get(stage, []))
    overrides = self_tuning.read_overrides(root)
    stage_overlay = overrides.get(stage, {})
    remove_ids = set(stage_overlay.get("remove", [])) - {
        gid for (s, gid) in self_tuning.PROTECTED_REMOVALS if s == stage
    }
    result = [entry for entry in baseline if entry[0] not in remove_ids]
    existing_ids = {entry[0] for entry in result}
    for gate_id in stage_overlay.get("add", []):
        if gate_id not in existing_ids:
            # Added-by-overlay gates carry no known script/flag -- this is
            # a placeholder membership entry for a gate that must already
            # exist as a real STAGE_GATES entry somewhere else (this
            # function does not invent new gate scripts). Real usage of
            # "add" is for re-enabling a gate on a stage it's not normally
            # attached to, using that gate's own real script/flag spec.
            for other_stage, other_entries in STAGE_GATES.items():
                match = next((e for e in other_entries if e[0] == gate_id), None)
                if match:
                    result.append(match)
                    existing_ids.add(gate_id)
                    break
    return result
```

Also add gate-history logging: read `run_gate()`'s full current body first, then wrap its return with a history-append call. At the end of `run_gate()`, immediately before `return GateResult(gate_id, script_ok, detail)` (there may be more than one such return statement on different branches — check by reading the function fully; add the logging call before EVERY return that produces a real (not tool-missing) result):

```python
    from . import self_tuning as _self_tuning
    try:
        _self_tuning.append_gate_history(
            root, gate_id, stage or "", bool(script_ok), str(detail.get("reason", detail.get("status", ""))),
            __import__("time").time(),
        )
    except Exception:
        pass
    return GateResult(gate_id, script_ok, detail)
```

(Use `import time` at the top of `gates.py` instead of the inline `__import__` if `time` is not already imported — check the file's existing imports first and add a normal `import time` there if missing, using the inline form only if a top-level import would conflict with something already named `time` in that module, which is unlikely.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest dv_harness_tests/test_self_tuning.py -v`
Expected: all PASS. Also run `python -m pytest dv_harness_tests/test_engine_gates_and_routing.py dv_harness_tests/test_hard_gate_script_smoke.py -v` to confirm the `run_gate()` change doesn't break any existing gate invocation (the history-append is wrapped in try/except and must never change `run_gate()`'s return value or raise).
Expected: all PASS, same counts as before this task.

- [ ] **Step 5: Commit**

```bash
git add dv_harness/gates.py dv_harness_tests/test_self_tuning.py
git commit -m "feat: add effective_stage_gates() overlay + gate_history logging in run_gate()"
```

---

### Task 3: `tools/verification_flow/self_tuning_proposal_gate.py`

**Files:**
- Create: `tools/verification_flow/self_tuning_proposal_gate.py`
- Test: `dv_harness_tests/test_self_tuning_proposal_gate.py`

**Interfaces:**
- Consumes: none from earlier tasks at the Python-import level (this is a standalone subprocess-invoked script, per this codebase's existing gate-script convention — read `tools/verification_flow/manual_lookup_before_edit_gate.py` first for the standard shape: argparse a single positional flag holding a path to a JSON payload file, print a JSON result to stdout, `sys.exit(0)` on success / nonzero on failure).
- Produces: invoked via `run_gate(root, "self_tuning_proposal_gate.py", "--proposal", payload)` where `payload = {"proposals": [...]}`. On success (exit 0), stdout JSON has `{"status": "PASS", "surviving_proposals": [...], "stripped": [...]}`. `surviving_proposals` and `stripped` are both lists of the same proposal-dict shape as the input, annotated with a `"strip_reason"` key added to each stripped entry.

**Parameter-exposure-protected gate_ids** (from the spec — a proposal whose `change.param` targets one of these specific `(gate_id, param)` pairs is always stripped, in addition to the removal-protection check):
- `("fix_risk_approval_gate", "risk_classification_threshold")`
- `("deep_rca_evidence_gate", "min_hypothesis_count")`
- `("root_cause_evidence_gate", "min_hypothesis_count")`
- `("regression_submission_policy_gate", "wave_default_off")`
- `("regression_submission_policy_gate", "require_prior_failure_ref")`

- [ ] **Step 1: Write the failing tests**

```python
# dv_harness_tests/test_self_tuning_proposal_gate.py
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "verification_flow" / "self_tuning_proposal_gate.py"


def _run(payload):
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(payload, f)
        path = f.name
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--proposal", path],
        cwd=str(ROOT), capture_output=True, text=True, timeout=30,
    )
    return proc.returncode, json.loads(proc.stdout)


def test_normal_proposal_passes_through_unmodified():
    rc, out = _run({"proposals": [
        {"gate_id": "some_unprotected_gate", "change": {"param": "window_us", "from": 200, "to": 250},
         "rationale": "observed pattern", "confidence": "HIGH", "risk_level": "LOW"},
    ]})
    assert rc == 0
    assert out["status"] == "PASS"
    assert len(out["surviving_proposals"]) == 1
    assert out["stripped"] == []


def test_removal_of_protected_gate_is_stripped():
    rc, out = _run({"proposals": [
        {"gate_id": "fix_risk_approval_gate", "stage": "RE_AUDIT",
         "change": {"action": "remove", "gate_id": "fix_risk_approval_gate"},
         "rationale": "seems redundant", "confidence": "HIGH", "risk_level": "LOW"},
    ]})
    assert rc == 0
    assert out["surviving_proposals"] == []
    assert len(out["stripped"]) == 1
    assert out["stripped"][0]["strip_reason"] == "PROTECTED_REMOVAL"


def test_protected_parameter_exposure_is_stripped():
    rc, out = _run({"proposals": [
        {"gate_id": "fix_risk_approval_gate",
         "change": {"param": "risk_classification_threshold", "from": 0.5, "to": 0.8},
         "rationale": "reduce false positives", "confidence": "HIGH", "risk_level": "LOW"},
    ]})
    assert rc == 0
    assert out["surviving_proposals"] == []
    assert out["stripped"][0]["strip_reason"] == "PROTECTED_PARAMETER"


def test_missing_proposals_key_fails():
    rc, out = _run({})
    assert rc != 0
    assert out["status"] == "FAIL"


def test_proposal_missing_required_field_is_stripped_not_crashed():
    rc, out = _run({"proposals": [
        {"gate_id": "some_gate", "change": {"param": "x", "from": 1, "to": 2}},
    ]})
    assert rc == 0
    assert out["surviving_proposals"] == []
    assert out["stripped"][0]["strip_reason"] == "MISSING_REQUIRED_FIELD"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest dv_harness_tests/test_self_tuning_proposal_gate.py -v`
Expected: FAIL (script doesn't exist yet -- subprocess exits nonzero / stdout empty)

- [ ] **Step 3: Implement**

```python
# tools/verification_flow/self_tuning_proposal_gate.py
"""Mechanically enforces the autonomous gate self-tuning protected list
against an LLM-proposed batch of adjustments -- see
docs/superpowers/specs/2026-09-02-autonomous-gate-self-tuning-design.md's
"Safety boundary" section. This is the real backstop: the protected list
is enforced HERE in code, not merely described in the analysis prompt the
LLM saw."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from dv_harness.self_tuning import PROTECTED_REMOVALS  # noqa: E402

PROTECTED_PARAMETERS = {
    ("fix_risk_approval_gate", "risk_classification_threshold"),
    ("deep_rca_evidence_gate", "min_hypothesis_count"),
    ("root_cause_evidence_gate", "min_hypothesis_count"),
    ("regression_submission_policy_gate", "wave_default_off"),
    ("regression_submission_policy_gate", "require_prior_failure_ref"),
}

REQUIRED_FIELDS = {"gate_id", "change", "rationale", "confidence", "risk_level"}


def _strip_reason(proposal):
    if not REQUIRED_FIELDS.issubset(proposal.keys()):
        return "MISSING_REQUIRED_FIELD"
    change = proposal.get("change") or {}
    if change.get("action") == "remove":
        stage = proposal.get("stage", "")
        target_gate = change.get("gate_id", proposal.get("gate_id"))
        if (stage, target_gate) in PROTECTED_REMOVALS:
            return "PROTECTED_REMOVAL"
        return None
    param = change.get("param")
    if param is not None and (proposal.get("gate_id"), param) in PROTECTED_PARAMETERS:
        return "PROTECTED_PARAMETER"
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--proposal", required=True)
    a = ap.parse_args()

    try:
        payload = json.loads(Path(a.proposal).read_text(encoding="utf-8"))
    except Exception as e:
        print(json.dumps({"status": "FAIL", "reason": "PAYLOAD_UNREADABLE", "detail": str(e)}))
        return 2

    proposals = payload.get("proposals")
    if not isinstance(proposals, list):
        print(json.dumps({"status": "FAIL", "reason": "MISSING_PROPOSALS_LIST"}))
        return 2

    surviving = []
    stripped = []
    for p in proposals:
        if not isinstance(p, dict):
            stripped.append({"strip_reason": "NOT_A_DICT", "raw": p})
            continue
        reason = _strip_reason(p)
        if reason:
            entry = dict(p)
            entry["strip_reason"] = reason
            stripped.append(entry)
        else:
            surviving.append(p)

    print(json.dumps({"status": "PASS", "surviving_proposals": surviving, "stripped": stripped}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest dv_harness_tests/test_self_tuning_proposal_gate.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add tools/verification_flow/self_tuning_proposal_gate.py dv_harness_tests/test_self_tuning_proposal_gate.py
git commit -m "feat: add self_tuning_proposal_gate.py mechanical safety enforcement"
```

---

### Task 4: Apply/defer classification + adjustment record persistence

**Files:**
- Modify: `dv_harness/self_tuning.py` (add to the file from Task 1)
- Test: `dv_harness_tests/test_self_tuning.py` (add to the file from Task 1)

**Interfaces:**
- Consumes: `dv_harness.memory_router.route_and_store(root, record, cfg=None) -> dict` (existing, real signature confirmed in this codebase -- `cfg=None` now auto-loads the project's config per the 2026-09-02 fix, but this feature must NOT let a `self_tuning_adjustment` record reach the shared Knowledge Center regardless -- see Step 3).
- Produces:
  - `ELEVATED_SCRUTINY_GATES: set` — hardcoded set of gate_ids: `{"deep_rca_evidence_gate", "root_cause_evidence_gate", "focused_wave_debug_window_gate", "fix_regression_non_regression_gate", "issue_triage_classification_gate", "unknown_failure_escalation_gate", "failure_signature_recurrence_gate", "failure_attribution", "nondeterminism_attribution_gate", "rca_confidence_escalation_gate", "regression_replay_equivalence_gate", "root_cause_attribution_consistency_gate", "dut_request_record_gate", "rca_replay_fix_closure_gate"}` (every gate currently in `STAGE_GATES["RE_AUDIT"]`/`["FAILURE_RECOVERY"]` not already in the removal-protected list)
  - `classify_proposal(proposal: dict, cycle_proposals: list, recent_reverts: set) -> str` — returns `"AUTO_APPLY"` or `"DEFER"`. Pure function, no I/O.
  - `record_adjustment(root: Path, proposal: dict, status: str, applied_by: str = "system") -> str` — builds and stores a `kind="self_tuning_adjustment"` record via a LOCAL-ONLY store (never `route_and_store`, since that could share to KC for a future `kind` this feature doesn't control -- write directly via `dv_harness.memory.MemoryStore(root).add("project", record)`, which is the existing per-project store, non-shareable by `memory_router._SHAREABLE_DESTINATIONS`'s own design). Returns the new `memory_id`.
  - `apply_proposal(root: Path, proposal: dict) -> None` — performs the actual `set_param`/`propose_add_override`/`propose_remove_override` call per `proposal["change"]`'s shape.

- [ ] **Step 1: Write the failing tests**

Append to `dv_harness_tests/test_self_tuning.py`:

```python
from dv_harness.self_tuning import (
    classify_proposal, ELEVATED_SCRUTINY_GATES, record_adjustment, apply_proposal,
    get_param, read_overrides,
)


def _param_proposal(gate_id="unprotected_gate", confidence="HIGH", risk_level="LOW"):
    return {
        "gate_id": gate_id, "change": {"param": "threshold", "from": 5, "to": 6},
        "rationale": "r", "confidence": confidence, "risk_level": risk_level,
    }


def test_classify_auto_applies_high_confidence_low_risk_single_change():
    p = _param_proposal()
    assert classify_proposal(p, cycle_proposals=[p], recent_reverts=set()) == "AUTO_APPLY"


def test_classify_defers_on_low_confidence():
    p = _param_proposal(confidence="LOW")
    assert classify_proposal(p, cycle_proposals=[p], recent_reverts=set()) == "DEFER"


def test_classify_defers_on_high_risk():
    p = _param_proposal(risk_level="HIGH")
    assert classify_proposal(p, cycle_proposals=[p], recent_reverts=set()) == "DEFER"


def test_classify_defers_removal_action():
    p = {"gate_id": "g", "stage": "COMMAND_PATTERN",
         "change": {"action": "remove", "gate_id": "g"},
         "rationale": "r", "confidence": "HIGH", "risk_level": "LOW"}
    assert classify_proposal(p, cycle_proposals=[p], recent_reverts=set()) == "DEFER"


def test_classify_defers_elevated_scrutiny_gate():
    gate_id = next(iter(ELEVATED_SCRUTINY_GATES))
    p = _param_proposal(gate_id=gate_id)
    assert classify_proposal(p, cycle_proposals=[p], recent_reverts=set()) == "DEFER"


def test_classify_defers_multi_gate_cycle():
    p1 = _param_proposal(gate_id="gate_a")
    p2 = _param_proposal(gate_id="gate_b")
    assert classify_proposal(p1, cycle_proposals=[p1, p2], recent_reverts=set()) == "DEFER"


def test_classify_defers_recently_reverted_gate():
    p = _param_proposal(gate_id="gate_a")
    assert classify_proposal(p, cycle_proposals=[p], recent_reverts={"gate_a"}) == "DEFER"


def test_apply_proposal_sets_param():
    root = _tmp_root()
    try:
        apply_proposal(root, _param_proposal())
        assert get_param(root, "unprotected_gate", "threshold", None) == 6
    finally:
        shutil.rmtree(root)


def test_apply_proposal_adds_override():
    root = _tmp_root()
    try:
        p = {"gate_id": "g", "stage": "COMMAND_PATTERN",
             "change": {"action": "add", "gate_id": "g"},
             "rationale": "r", "confidence": "HIGH", "risk_level": "LOW"}
        apply_proposal(root, p)
        assert "g" in read_overrides(root)["COMMAND_PATTERN"]["add"]
    finally:
        shutil.rmtree(root)


def test_record_adjustment_stores_locally_not_shared():
    root = _tmp_root()
    try:
        mem_id = record_adjustment(root, _param_proposal(), status="APPLIED")
        assert mem_id.startswith("MEM-")
        stored = json.loads((root / ".dv-harness" / "memory" / "project" / f"{mem_id}.json").read_text(encoding="utf-8"))
        assert stored["kind"] == "self_tuning_adjustment"
        assert stored["status"] == "APPLIED"
    finally:
        shutil.rmtree(root)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest dv_harness_tests/test_self_tuning.py -v -k "classify or apply_proposal or record_adjustment"`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement**

Append to `dv_harness/self_tuning.py`:

```python
ELEVATED_SCRUTINY_GATES = {
    "deep_rca_evidence_gate", "root_cause_evidence_gate",
    "focused_wave_debug_window_gate", "fix_regression_non_regression_gate",
    "issue_triage_classification_gate", "unknown_failure_escalation_gate",
    "failure_signature_recurrence_gate", "failure_attribution",
    "nondeterminism_attribution_gate", "rca_confidence_escalation_gate",
    "regression_replay_equivalence_gate", "root_cause_attribution_consistency_gate",
    "dut_request_record_gate", "rca_replay_fix_closure_gate",
}


def classify_proposal(proposal: Dict[str, Any], cycle_proposals: List[Dict[str, Any]],
                       recent_reverts: set) -> str:
    """Pure classification -- see the design spec's "Apply / defer-to-human"
    section for the exact rule list. No I/O; callers pass in whatever
    context (this cycle's full proposal batch, the set of gate_ids
    reverted in recent cycles) they've already assembled."""
    change = proposal.get("change") or {}
    if proposal.get("confidence") != "HIGH":
        return "DEFER"
    if proposal.get("risk_level") == "HIGH":
        return "DEFER"
    if change.get("action") in ("remove",):
        return "DEFER"
    if proposal.get("gate_id") in ELEVATED_SCRUTINY_GATES:
        return "DEFER"
    if len(cycle_proposals) > 1:
        return "DEFER"
    if proposal.get("gate_id") in recent_reverts:
        return "DEFER"
    return "AUTO_APPLY"


def apply_proposal(root: Path, proposal: Dict[str, Any]) -> None:
    change = proposal.get("change") or {}
    action = change.get("action")
    if action == "add":
        propose_add_override(root, proposal["stage"], change["gate_id"])
    elif action == "remove":
        propose_remove_override(root, proposal["stage"], change["gate_id"])
    else:
        set_param(root, proposal["gate_id"], change["param"], change["to"])


def record_adjustment(root: Path, proposal: Dict[str, Any], status: str,
                       applied_by: str = "system") -> str:
    from .memory import MemoryStore
    record = {
        "kind": "self_tuning_adjustment",
        "status": status,
        "applied_by": applied_by,
        "gate_id": proposal.get("gate_id"),
        "stage": proposal.get("stage"),
        "change": proposal.get("change"),
        "rationale": proposal.get("rationale"),
        "confidence": proposal.get("confidence"),
        "risk_level": proposal.get("risk_level"),
    }
    stored = MemoryStore(root).add("project", record)
    return stored["memory_id"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest dv_harness_tests/test_self_tuning.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add dv_harness/self_tuning.py dv_harness_tests/test_self_tuning.py
git commit -m "feat: add self-tuning proposal classification (auto-apply vs defer) and adjustment recording"
```

---

### Task 5: Review-cycle orchestration wired into `engine.py`

**Files:**
- Modify: `dv_harness/engine.py` (read `_promote_verified_fix_knowledge`'s full method and its call site inside `run_stage()` FIRST -- this task's new method follows the exact same shape/call-site pattern)
- Modify: `dv_harness/config.py` (add `self_tuning` section to `DEFAULT_CONFIG`)
- Test: `dv_harness_tests/test_engine_gates_and_routing.py` (add to existing file)

**Interfaces:**
- Consumes: `dv_harness.self_tuning.{increment_execution_counter, reset_execution_counter, read_gate_history_since, gate_history_length, classify_proposal, apply_proposal, record_adjustment}` (Tasks 1+4), `dv_harness.gates.{extract_evidence_blocks, run_gate}` (existing + Task 3's new script), `self.adapter.run(prompt, cwd) -> AgentResult` (existing, `AgentResult.text`/`.ok` fields).
- Produces: `DVHarness._maybe_run_self_tuning_review() -> None` (best-effort, called once per real terminal `run_stage()` result -- find the exact call site by reading how `_promote_verified_fix_knowledge(stage, evidence_blocks)` is invoked in `run_stage()`'s PASS branch, and add this new call in the SAME general vicinity but unconditional on stage/verdict, since self-tuning reviews accumulated history regardless of which stage just ran or whether it passed).

- [ ] **Step 1: Write the failing tests**

Add to `dv_harness_tests/test_engine_gates_and_routing.py`. This file's real, confirmed construction pattern for a `DVHarness` with a fake adapter (used verbatim elsewhere in this file, e.g. around line 3260) is: `DVHarness(tmp)` against a fresh `tempfile.mkdtemp()` path, with `h.adapter` replaced by a small class implementing `run(self, prompt, cwd, resume_session=None, agent_profile=None) -> AgentResult`. These tests call `_maybe_run_self_tuning_review()` directly (not through `run_stage()`), so no `main_graph.json`/stage setup is needed — only `DVHarness(tmp)` + a fake adapter:

```python
import shutil
import tempfile
from pathlib import Path
from dv_harness import self_tuning
from dv_harness.engine import DVHarness
from dv_harness.adapters.base import AgentResult


class _FakeSelfTuningAdapter:
    def __init__(self, text=None, ok=True, raises=None):
        self.text = text
        self.ok = ok
        self.raises = raises
        self.calls = 0

    def run(self, prompt, cwd, resume_session=None, agent_profile=None):
        self.calls += 1
        if self.raises:
            raise self.raises
        return AgentResult(ok=self.ok, text=self.text or "", raw={}, session_id="s")


def _proposal_block(gate_id="unprotected_gate", confidence="HIGH", risk_level="LOW", to=2):
    import json as _json
    return (
        "```dv-harness-evidence:self_tuning_proposal\n"
        + _json.dumps({"proposals": [{
            "gate_id": gate_id, "change": {"param": "threshold", "from": 1, "to": to},
            "rationale": "observed pattern", "confidence": confidence, "risk_level": risk_level,
        }]})
        + "\n```"
    )


def test_self_tuning_review_triggers_after_n_executions_and_auto_applies():
    tmp = Path(tempfile.mkdtemp())
    try:
        h = DVHarness(tmp)
        h.cfg["self_tuning"] = {"enabled": True, "review_every_n_executions": 2}
        fake = _FakeSelfTuningAdapter(text=_proposal_block())
        h.adapter = fake

        self_tuning.increment_execution_counter(h.root)  # 1st of 2
        h._maybe_run_self_tuning_review()
        assert fake.calls == 0

        self_tuning.increment_execution_counter(h.root)  # 2nd of 2 -- triggers
        h._maybe_run_self_tuning_review()
        assert fake.calls == 1

        assert self_tuning.get_param(h.root, "unprotected_gate", "threshold", None) == 2
        assert self_tuning.read_execution_state(h.root)["executions_since_last_review"] == 0
    finally:
        shutil.rmtree(tmp)


def test_self_tuning_review_defers_low_confidence_proposal():
    tmp = Path(tempfile.mkdtemp())
    try:
        h = DVHarness(tmp)
        h.cfg["self_tuning"] = {"enabled": True, "review_every_n_executions": 1}
        h.adapter = _FakeSelfTuningAdapter(text=_proposal_block(confidence="LOW"))

        self_tuning.increment_execution_counter(h.root)
        h._maybe_run_self_tuning_review()

        assert self_tuning.get_param(h.root, "unprotected_gate", "threshold", None) is None
    finally:
        shutil.rmtree(tmp)


def test_self_tuning_review_disabled_by_default_config():
    tmp = Path(tempfile.mkdtemp())
    try:
        h = DVHarness(tmp)
        # no h.cfg["self_tuning"] override -- DEFAULT_CONFIG's own default applies
        fake = _FakeSelfTuningAdapter(text=_proposal_block())
        h.adapter = fake
        for _ in range(100):
            self_tuning.increment_execution_counter(h.root)
        h._maybe_run_self_tuning_review()
        assert fake.calls == 0
    finally:
        shutil.rmtree(tmp)


def test_self_tuning_review_adapter_failure_does_not_reset_counter_or_raise():
    tmp = Path(tempfile.mkdtemp())
    try:
        h = DVHarness(tmp)
        h.cfg["self_tuning"] = {"enabled": True, "review_every_n_executions": 1}
        h.adapter = _FakeSelfTuningAdapter(raises=RuntimeError("boom"))

        self_tuning.increment_execution_counter(h.root)
        h._maybe_run_self_tuning_review()  # must not raise

        assert self_tuning.read_execution_state(h.root)["executions_since_last_review"] == 1
    finally:
        shutil.rmtree(tmp)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest dv_harness_tests/test_engine_gates_and_routing.py -v -k self_tuning`
Expected: FAIL with `AttributeError: 'DVHarness' object has no attribute '_maybe_run_self_tuning_review'`

- [ ] **Step 3: Implement**

In `dv_harness/config.py`, add to `DEFAULT_CONFIG` (alongside the existing top-level keys like `"knowledge_center"`):

```python
    "self_tuning": {
        # Autonomous gate self-tuning (2026-09-02 design). Disabled by
        # default -- a project must explicitly opt in. See
        # docs/superpowers/specs/2026-09-02-autonomous-gate-self-tuning-design.md.
        "enabled": False,
        "review_every_n_executions": 20,
    },
```

In `dv_harness/engine.py`, add a new method on `DVHarness` (place it near `_promote_verified_fix_knowledge`, matching that method's style):

```python
    def _maybe_run_self_tuning_review(self) -> None:
        """Best-effort autonomous gate self-tuning review -- see
        docs/superpowers/specs/2026-09-02-autonomous-gate-self-tuning-design.md.
        Called once per real terminal run_stage() result, regardless of
        stage/verdict (self-tuning reviews accumulated cross-stage history,
        not any one stage's own evidence). Any failure here must never
        break or block the real stage result it's piggybacking on."""
        try:
            from . import self_tuning
            from .gates import extract_evidence_blocks, run_gate

            st_cfg = (self.cfg or {}).get("self_tuning", {}) or {}
            if not st_cfg.get("enabled"):
                return
            n = int(st_cfg.get("review_every_n_executions", 20))
            state = self_tuning.read_execution_state(self.root)
            if state.get("executions_since_last_review", 0) < n:
                return

            history = self_tuning.read_gate_history_since(self.root, 0)
            prompt = (
                "You are reviewing accumulated real gate-execution history to "
                "propose self-tuning adjustments. Evidence (most recent "
                f"{len(history)} gate invocations):\n" + json.dumps(history) +
                "\n\nRespond with a single fenced "
                "```dv-harness-evidence:self_tuning_proposal``` block containing "
                '{"proposals": [{"gate_id":..., "stage":... (only for add/remove '
                'changes), "change": {"param":...,"from":...,"to":...} OR '
                '{"action":"add"|"remove","gate_id":...}, "rationale":..., '
                '"confidence":"HIGH"|"MEDIUM"|"LOW", "risk_level":"LOW"|"HIGH"}]}. '
                "Propose zero or more adjustments; an empty list is a valid, "
                "honest answer when the evidence doesn't support any change."
            )
            result = self.adapter.run(prompt=prompt, cwd=str(self.root))
            if not result or not getattr(result, "ok", False):
                return  # counter NOT reset -- retried at the next real run_stage()

            blocks = extract_evidence_blocks(result.text or "")
            evidence = blocks.get("self_tuning_proposal")
            if not evidence:
                self_tuning.reset_execution_counter(self.root)
                return

            gate_result = run_gate(self.root, "self_tuning_proposal_gate.py", "--proposal", evidence)
            if not gate_result.ok:
                self_tuning.reset_execution_counter(self.root)
                return

            surviving = gate_result.detail.get("surviving_proposals", [])
            for proposal in surviving:
                verdict = self_tuning.classify_proposal(proposal, surviving, recent_reverts=set())
                if verdict == "AUTO_APPLY":
                    self_tuning.apply_proposal(self.root, proposal)
                    self_tuning.record_adjustment(self.root, proposal, status="APPLIED")
                else:
                    self_tuning.record_adjustment(self.root, proposal, status="PENDING")

            self_tuning.reset_execution_counter(self.root)
        except Exception:
            pass
```

Add `import json` at the top of `engine.py` if not already imported (check first — this file almost certainly already imports `json` given how much JSON handling it does elsewhere; only add if genuinely missing).

Call this method once per real terminal `run_stage()` result. Read `run_stage()`'s full body to find where the counter should increment (once per call, regardless of verdict) and where the review should be attempted (after that increment, near the end of the method, alongside the existing `_promote_*` calls in the PASS branch — but this call itself must NOT be inside an `if verdict == PASS` guard, since the design increments on every terminal verdict, not only PASS). Add:

```python
        from . import self_tuning
        self_tuning.increment_execution_counter(self.root)
        self._maybe_run_self_tuning_review()
```

near `run_stage()`'s return point(s), after the verdict has been finally determined (this may mean adding it at more than one return path if `run_stage()` has multiple exits for different verdicts — read the method fully to find every terminal return and add the same two lines before each, or refactor to a single exit point if one already exists; do not skip any verdict-producing path).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest dv_harness_tests/test_engine_gates_and_routing.py -v -k self_tuning`
Expected: all PASS

Then run the full file to confirm no regression from touching `run_stage()`'s exit paths:

Run: `python -m pytest dv_harness_tests/test_engine_gates_and_routing.py -v`
Expected: all PASS, same count as before this task plus the new self-tuning tests

- [ ] **Step 5: Commit**

```bash
git add dv_harness/engine.py dv_harness/config.py dv_harness_tests/test_engine_gates_and_routing.py
git commit -m "feat: wire self-tuning review cycle into run_stage()"
```

---

### Task 6: CLI subcommands

**Files:**
- Modify: `dv_harness/cli.py` (read the existing `knowledge` subcommand group's argparse setup first -- e.g. `pkc = sub.add_parser(...)`, `pkc_sub = pkc.add_subparsers(...)` -- for the exact pattern to follow for a new `self-tune` subcommand group)
- Test: `dv_harness_tests/test_self_tuning.py` or a new `dv_harness_tests/test_self_tuning_cli.py` if the existing file's test style is unit-level (import functions directly) rather than CLI-invocation-level -- check `test_engine_gates_and_routing.py`'s or `test_knowledge_center.py`'s CLI-testing style first (likely invoking `dv_harness.cli.main()` with `monkeypatch.setattr(sys, "argv", [...])`, matching the pattern already used for `remote_exec.py`'s CLI tests) and match it.

**Interfaces:**
- Consumes: `dv_harness.self_tuning.{read_execution_state, ...}` (Tasks 1+4). `dv_harness.memory.MemoryStore`'s REAL, CONFIRMED API (read `dv_harness/memory.py` lines 8-64 — there is no `.list()`/`.update()`): `add(level: str, memory: dict) -> dict` (mints a new `memory_id` if `memory` doesn't already carry one; if it DOES carry one, overwrites that exact record in place — this is how "update" is done, by re-adding with the same `memory_id` already set), `get(memory_id: str) -> Optional[dict]`, and the private `_index()` (returns summary rows for every stored memory across all levels, each row having `memory_id`/`level`/`title`/... but NOT arbitrary custom fields like `kind`/`gate_id` — use it only to enumerate candidate `memory_id`s for a level, then `get()` each one for the full record to filter on `kind`).
- Produces: `dv-harness self-tune status`, `dv-harness self-tune list [--pending|--applied]`, `dv-harness self-tune approve <id>`, `dv-harness self-tune reject <id>`, `dv-harness self-tune revert <id>`.

- [ ] **Step 1: Write the failing test**

```python
# dv_harness_tests/test_self_tuning_cli.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest dv_harness_tests/test_self_tuning_cli.py -v`
Expected: FAIL (`self-tune` not a recognized subcommand)

- [ ] **Step 3: Implement**

In `dv_harness/cli.py`, find `sub = ap.add_subparsers(...)` (the top-level subparser registration all other subcommands use) and add, following the exact style of the nearest existing multi-level subcommand group (`knowledge`):

```python
    pst = sub.add_parser("self-tune", help="Autonomous gate self-tuning: status/list/approve/reject/revert. "
                                           "See dv_harness/self_tuning.py and docs/superpowers/specs/"
                                           "2026-09-02-autonomous-gate-self-tuning-design.md.")
    pst_sub = pst.add_subparsers(dest="self_tune_cmd", required=True)
    pst_status = pst_sub.add_parser("status")
    pst_list = pst_sub.add_parser("list")
    pst_list.add_argument("--pending", action="store_true")
    pst_list.add_argument("--applied", action="store_true")
    pst_approve = pst_sub.add_parser("approve")
    pst_approve.add_argument("memory_id")
    pst_reject = pst_sub.add_parser("reject")
    pst_reject.add_argument("memory_id")
    pst_revert = pst_sub.add_parser("revert")
    pst_revert.add_argument("memory_id")
```

Find `main()`'s real dispatch chain — it is `if/elif args.cmd == "<name>":` (the top-level subparsers' real `dest` is `"cmd"`, confirmed at `sub = ap.add_subparsers(dest="cmd", required=True)`; do not use `args.command`, which does not exist) — and add a new `elif` arm at the end of that chain, following the `knowledge`/`pkc_sub` arm's style (`dest="kc_cmd"` there, `dest="self_tune_cmd"` here — same naming convention this codebase already uses for `bb_cmd`/`rc_cmd`/`config_cmd`/`kc_cmd`):

```python
    elif args.cmd == "self-tune":
        from . import self_tuning
        from .memory import MemoryStore
        root = Path(args.project_root)
        store = MemoryStore(root)

        def _project_self_tuning_records():
            ids = [r["memory_id"] for r in store._index() if r.get("level") == "project"]
            out = []
            for mid in ids:
                rec = store.get(mid)
                if rec and rec.get("kind") == "self_tuning_adjustment":
                    out.append(rec)
            return out

        if args.self_tune_cmd == "status":
            print(json.dumps(self_tuning.read_execution_state(root)))
            return 0
        if args.self_tune_cmd == "list":
            records = _project_self_tuning_records()
            if args.pending:
                records = [r for r in records if r.get("status") == "PENDING"]
            if args.applied:
                records = [r for r in records if r.get("status") == "APPLIED"]
            print(json.dumps({"records": records}))
            return 0
        if args.self_tune_cmd == "approve":
            record = store.get(args.memory_id)
            if not record or record.get("status") != "PENDING":
                print(json.dumps({"ok": False, "error": "NOT_FOUND_OR_NOT_PENDING"}))
                return 1
            proposal = {"gate_id": record.get("gate_id"), "stage": record.get("stage"),
                        "change": record.get("change"), "rationale": record.get("rationale"),
                        "confidence": record.get("confidence"), "risk_level": record.get("risk_level")}
            self_tuning.apply_proposal(root, proposal)
            record["status"] = "APPLIED"
            store.add("project", record)  # same memory_id already in record -> overwrites in place
            print(json.dumps({"ok": True, "memory_id": args.memory_id}))
            return 0
        if args.self_tune_cmd == "reject":
            record = store.get(args.memory_id)
            if not record:
                print(json.dumps({"ok": False, "error": "NOT_FOUND"}))
                return 1
            record["status"] = "REJECTED"
            store.add("project", record)
            print(json.dumps({"ok": True, "memory_id": args.memory_id}))
            return 0
        if args.self_tune_cmd == "revert":
            record = store.get(args.memory_id)
            if not record or record.get("status") != "APPLIED":
                print(json.dumps({"ok": False, "error": "NOT_FOUND_OR_NOT_APPLIED"}))
                return 1
            change = record.get("change") or {}
            if change.get("action") == "add":
                # Revert an add: remove it from the overlay's add list.
                overrides = self_tuning.read_overrides(root)
                stage_entry = overrides.get(record.get("stage"), {})
                if change.get("gate_id") in stage_entry.get("add", []):
                    stage_entry["add"].remove(change["gate_id"])
                self_tuning._write_json_atomic(self_tuning._overrides_path(root), overrides)
            elif change.get("action") == "remove":
                overrides = self_tuning.read_overrides(root)
                stage_entry = overrides.get(record.get("stage"), {})
                if change.get("gate_id") in stage_entry.get("remove", []):
                    stage_entry["remove"].remove(change["gate_id"])
                self_tuning._write_json_atomic(self_tuning._overrides_path(root), overrides)
            else:
                self_tuning.set_param(root, record.get("gate_id"), change.get("param"), change.get("from"))
            record["status"] = "REVERTED"
            store.add("project", record)
            print(json.dumps({"ok": True, "memory_id": args.memory_id}))
            return 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest dv_harness_tests/test_self_tuning_cli.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add dv_harness/cli.py dv_harness_tests/test_self_tuning_cli.py
git commit -m "feat: add dv-harness self-tune status/list/approve/reject/revert CLI"
```

---

## Self-Review Notes (fill in during execution, not before)

Per the writing-plans skill, the implementer/controller must re-run the 3-point self-review (spec coverage, placeholder scan, type consistency) once all 6 tasks are complete, before finishing-a-development-branch — this section is a reminder, not a substitute for actually doing it.
