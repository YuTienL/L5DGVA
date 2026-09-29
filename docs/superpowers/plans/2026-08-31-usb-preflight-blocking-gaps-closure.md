# USB Pre-Flight Blocking Gaps Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the 4 BLOCKING gaps (B1–B4) found by the 2026-08-31 full-harness wiring audit, so the first real USB VIP-based UVM environment generation run has a real code-level reference-mining barrier, a real (generalized) profile/vip-lookup binding check, no dead alternate USB skills left reachable, and a real relocated remote-execution bridge with independent provenance verification.

**Architecture:** 5 tasks. Task 1 is a mechanical skill archival (no shared files with the others). Tasks 2, 3, and 5 each add one new gate script, one `STAGE_GATES` entry in `dv_harness/gates.py`, one entry in `.dv-harness/workflow/hard_gate_registry.json`'s `gates` list, and one entry in `dv_harness_tests/test_hard_gate_script_smoke.py`'s `ALL_GATE_TOOL_FILES` list — these three files are touched by 3 different tasks, so each task must APPEND to the existing list/dict rather than assume it owns the whole file (SDD runs implementers sequentially, so each task sees the prior task's committed additions). Task 4 relocates the persistent-relay scripts; Task 5 depends on Task 4 having landed first (its gate references the real relocated `remote_exec.py` output format and its docstring/tests cite the new path).

**Tech Stack:** Python 3.14, pytest, argparse-based CLI gate scripts (existing `dv_harness/gates.py` `STAGE_GATES`/`run_gate()` convention).

**Spec:** `docs/superpowers/specs/2026-08-31-usb-preflight-blocking-gaps-closure-design.md`

## Global Constraints

- Every gate script: argparse-based CLI, prints exactly one JSON line (`{"status": "PASS"|"FAIL", ...}`) to stdout, exits 0 for PASS / non-zero for FAIL, `--help` must exit 0 with non-empty output (required by the existing `test_gate_script_argparse_smoke` parametrized test in `test_hard_gate_script_smoke.py`).
- Every new gate must be registered in exactly 3 places, kept consistent: `dv_harness/gates.py`'s `STAGE_GATES` dict, `.dv-harness/workflow/hard_gate_registry.json`'s `gates` list (alphabetically sorted by `gate_id`, matching the file's existing convention), and `dv_harness_tests/test_hard_gate_script_smoke.py`'s `ALL_GATE_TOOL_FILES` list (alphabetically sorted, matching the file's existing convention) — the existing `test_gate_tool_list_matches_registry` test fails loudly if these 2 lists drift from each other, so both must be updated in the same task.
- Every gate's integration test uses the existing `_run_gate_script(rel_path, flag, payload)` helper already defined in `dv_harness_tests/test_engine_gates_and_routing.py` (relative path is under `tools/`, e.g. `"verification_flow/protocol_isolation_gate.py"`) — this calls the exact same `subprocess.run([sys.executable, script, flag, tmp_json_path], cwd=ROOT)` shape `dv_harness/gates.py`'s real `run_gate()` uses in production, so it is a real production-entrypoint-level test, not an internal-function-only unit test.
- `git mv` for any in-repo file relocation (preserves history); cross-repo relocation (Task 4) uses `cp` + independent content-diff verification + deletion of the old copy only after the new location's tests pass.
- File paths in evidence refs are relative to the project root (`ROOT`), matching `manual_lookup_before_edit_gate.py`'s and `run_gate()`'s existing `cwd=str(root)` convention.
- Full `dv_harness_tests/` suite (currently 1043 tests) must pass after every task, plus the new tests each task adds.

---

### Task 1: Archive 3 dead USB alternate-generation skills

**Files:**
- Move: `.claude/skills/REAL_ENV_GENERATION/usb-real-env-generator/SKILL.md` → `.claude/skills/_deprecated/REAL_ENV_GENERATION/usb-real-env-generator/SKILL.md`
- Move: `.claude/skills/REAL_PROJECT_GENERATION/usb-complete-env-generator/SKILL.md` → `.claude/skills/_deprecated/REAL_PROJECT_GENERATION/usb-complete-env-generator/SKILL.md`
- Move: `.claude/skills/UNIVERSAL_PROTOCOL/usb-production-builder/SKILL.md` → `.claude/skills/_deprecated/UNIVERSAL_PROTOCOL/usb-production-builder/SKILL.md`
- Modify: `dv_harness_tests/test_skill_resolver.py`

**Interfaces:**
- Consumes: `dv_harness/skill_resolver.py`'s existing `SkillResolver` class (unchanged — its `'_deprecated' not in p.relative_to(root).parts` filter, already covering 21 prior archived duplicates, automatically covers these 3 once moved; no code change needed in `skill_resolver.py` itself).
- Produces: nothing new consumed by later tasks.

- [ ] **Step 1: Read one already-archived sibling's NOTICE header for the exact wording to copy**

Read `.claude/skills/_deprecated/REAL_ENV_GENERATION/` — pick any one existing archived `SKILL.md` under it (e.g. `amba4-real-env-generator/SKILL.md`, `emmc-real-env-generator/SKILL.md`, or `ethernet-real-env-generator/SKILL.md` — all three were named directly in this session's audit findings) and read its NOTICE header in full so the new NOTICE text matches the established convention exactly (same section heading, same "duplicates X" phrasing, same date-of-archival format).

- [ ] **Step 2: Move the 3 files with git mv**

```bash
git mv ".claude/skills/REAL_ENV_GENERATION/usb-real-env-generator" ".claude/skills/_deprecated/REAL_ENV_GENERATION/usb-real-env-generator"
git mv ".claude/skills/REAL_PROJECT_GENERATION/usb-complete-env-generator" ".claude/skills/_deprecated/REAL_PROJECT_GENERATION/usb-complete-env-generator"
git mv ".claude/skills/UNIVERSAL_PROTOCOL/usb-production-builder" ".claude/skills/_deprecated/UNIVERSAL_PROTOCOL/usb-production-builder"
```

- [ ] **Step 3: Add/update each moved file's NOTICE header**

Edit each of the 3 moved `SKILL.md` files: add (or update, if a NOTICE already exists from the earlier audit's own read of the file) a NOTICE header matching the exact convention read in Step 1 — for each, the NOTICE states it duplicates `usb-environment-builder` (`.claude/skills/PROTOCOL_BUILDERS/usb-environment-builder`), is not referenced by `.dv-harness/builder/protocol_builder_registry.json`, any router `SKILL.md`, or any agent file, and was archived on 2026-08-31 per the full-harness wiring audit.

- [ ] **Step 4: Write the failing test**

Add to `dv_harness_tests/test_skill_resolver.py` (parametrize alongside the existing `test_deprecated_pcie_production_builder_not_resolvable_from_real_repo`, do not duplicate its body):

```python
import pytest


@pytest.mark.parametrize("skill_name", [
    "usb-real-env-generator",
    "usb-complete-env-generator",
    "usb-production-builder",
])
def test_deprecated_usb_alternate_generators_not_resolvable_from_real_repo(skill_name):
    resolver = SkillResolver(ROOT)
    assert skill_name not in resolver.index
    result = resolver.resolve([skill_name])[0]
    assert result["found"] is False
```

- [ ] **Step 5: Run test to verify it fails before Step 2/3 would have applied — actually run it now (Steps 2-3 already ran) to verify it PASSES**

Run: `python -m pytest dv_harness_tests/test_skill_resolver.py -v`
Expected: all tests including the 3 new parametrized cases PASS (the move already happened in Steps 2-3; this step is the real verification, not a red/green TDD cycle, since a pure file-move has no meaningful "write the test first against old code" step — moving the file IS the implementation).

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest -q`
Expected: 1043 + 3 = 1046 passed, 0 failed.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Task 1: archive 3 dead USB alternate-generation skills to _deprecated/"
```

---

### Task 2: `protocol_isolation_gate.py` (B1 — reference-mining barrier)

**Files:**
- Create: `tools/verification_flow/protocol_isolation_gate.py`
- Modify: `dv_harness/gates.py` (add `STAGE_GATES["IMPLEMENT"]` entry)
- Modify: `.dv-harness/workflow/hard_gate_registry.json` (append to `gates` list)
- Modify: `dv_harness_tests/test_hard_gate_script_smoke.py` (append to `ALL_GATE_TOOL_FILES`)
- Test: `dv_harness_tests/test_protocol_isolation_gate.py`
- Test: `dv_harness_tests/test_engine_gates_and_routing.py` (add integration tests)

**Interfaces:**
- Consumes: the same evidence-block shape `manual_lookup_before_edit_gate.py` already reads — specifically the `vip_evidence_refs` and `dut_rtl_evidence_refs` list-of-`{"path": ..., "quote": ...}` keys (confirmed exact key names by reading `tools/verification_flow/manual_lookup_before_edit_gate.py` directly — do not use any other key name).
- Produces: `FORBIDDEN_REFERENCE_TREES` tuple, importable by name from `tools/verification_flow/protocol_isolation_gate.py` for the test file to reference if needed (not required by other tasks).

- [ ] **Step 1: Write the failing tests**

Create `dv_harness_tests/test_protocol_isolation_gate.py`:

```python
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "verification_flow" / "protocol_isolation_gate.py"


def _run(payload):
    tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(payload, tmp)
    tmp.close()
    try:
        r = subprocess.run(
            [sys.executable, str(SCRIPT), "--edit", tmp.name],
            cwd=str(ROOT), capture_output=True, text=True, timeout=30,
        )
        out = json.loads((r.stdout or "").strip() or "{}")
        return r.returncode, out
    finally:
        Path(tmp.name).unlink(missing_ok=True)


def test_no_evidence_refs_at_all_is_a_pass():
    rc, out = _run({"branch": "block"})
    assert rc == 0 and out["status"] == "PASS"


def test_vip_evidence_ref_into_forbidden_tree_fails(tmp_path):
    forbidden_dir = tmp_path / "USB_UVM_Handoff" / "seq"
    forbidden_dir.mkdir(parents=True)
    forbidden_file = forbidden_dir / "usb_seq.sv"
    forbidden_file.write_text("class usb_seq;\nendclass\n", encoding="utf-8")
    rc, out = _run({
        "branch": "branch_b0",
        "vip_evidence_refs": [{"path": str(forbidden_file), "quote": "class usb_seq"}],
    })
    assert rc != 0 and out["status"] == "FAIL"
    assert out["reason"] == "REFERENCE_TREE_CITATION_FORBIDDEN"
    assert out["forbidden_tree"] == "USB_UVM_Handoff"


def test_dut_evidence_ref_into_forbidden_tree_fails(tmp_path):
    forbidden_dir = tmp_path / "USB_UVM_Handoff" / "rtl"
    forbidden_dir.mkdir(parents=True)
    forbidden_file = forbidden_dir / "usb_ctrl.v"
    forbidden_file.write_text("module usb_ctrl;\nendmodule\n", encoding="utf-8")
    rc, out = _run({
        "branch": "branch_a0",
        "dut_rtl_evidence_refs": [{"path": str(forbidden_file), "quote": "module usb_ctrl"}],
    })
    assert rc != 0 and out["status"] == "FAIL"
    assert out["reason"] == "REFERENCE_TREE_CITATION_FORBIDDEN"


def test_evidence_ref_into_real_vip_manual_passes(tmp_path):
    real_dir = tmp_path / "vip_manual"
    real_dir.mkdir()
    real_file = real_dir / "usb_vip_manual.md"
    real_file.write_text("class usb_seq;\nendclass\n", encoding="utf-8")
    rc, out = _run({
        "branch": "branch_b0",
        "vip_evidence_refs": [{"path": str(real_file), "quote": "class usb_seq"}],
    })
    assert rc == 0 and out["status"] == "PASS"


def test_substring_match_in_unrelated_filename_does_not_false_positive(tmp_path):
    # A filename that merely CONTAINS "USB_UVM_Handoff" as a substring, but
    # is not actually a path segment under that directory, must not trip
    # the forbidden-tree check -- it must match whole path segments only.
    real_dir = tmp_path / "notes"
    real_dir.mkdir()
    real_file = real_dir / "my_USB_UVM_Handoff_summary.md"
    real_file.write_text("summary text\n", encoding="utf-8")
    rc, out = _run({
        "branch": "branch_b0",
        "vip_evidence_refs": [{"path": str(real_file), "quote": "summary text"}],
    })
    assert rc == 0 and out["status"] == "PASS"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest dv_harness_tests/test_protocol_isolation_gate.py -v`
Expected: FAIL with `FileNotFoundError`/collection error (`protocol_isolation_gate.py` does not exist yet).

- [ ] **Step 3: Write the implementation**

Create `tools/verification_flow/protocol_isolation_gate.py`:

```python
#!/usr/bin/env python3
"""protocol_isolation_gate.py -- CLAUDE.md's "No Golden-Reference Content
Mining" rule was prompt-only until this gate (2026-08-31 full-harness
wiring audit, finding B1): nothing at code level stopped an agent from
citing content out of a reference environment (e.g. USB_UVM_Handoff) as if
it were a primary VIP/DUT source. This gate reads the same evidence-ref
shape manual_lookup_before_edit_gate.py already consumes and FAILs if any
cited path resolves into a forbidden reference tree. It never blocks
absence of evidence (that gate's job) -- only a confident, real citation
into a forbidden tree, which is worse than an honest absence.
"""
import argparse, json, pathlib, sys

# Path segments (not substrings) that mark a reference-environment tree an
# agent must never cite as if it were a primary source. Tuple, not a single
# string, so future projects' reference environments can be added without
# restructuring the check.
FORBIDDEN_REFERENCE_TREES = ("USB_UVM_Handoff",)


def _cites_forbidden_tree(path_str):
    parts = pathlib.Path(path_str).resolve().parts
    for forbidden in FORBIDDEN_REFERENCE_TREES:
        if forbidden in parts:
            return forbidden
    return None


def _check_refs(refs):
    if not isinstance(refs, list):
        return None
    for ref in refs:
        if not isinstance(ref, dict) or not ref.get("path"):
            continue
        forbidden = _cites_forbidden_tree(ref["path"])
        if forbidden:
            return forbidden, ref["path"]
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--edit", required=True)
    a = ap.parse_args()
    d = json.loads(pathlib.Path(a.edit).read_text())

    for key in ("vip_evidence_refs", "dut_rtl_evidence_refs"):
        hit = _check_refs(d.get(key))
        if hit:
            forbidden, path = hit
            print(json.dumps({
                "status": "FAIL", "reason": "REFERENCE_TREE_CITATION_FORBIDDEN",
                "field": key, "path": path, "forbidden_tree": forbidden,
            }))
            return 2

    print(json.dumps({"status": "PASS"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest dv_harness_tests/test_protocol_isolation_gate.py -v`
Expected: all 5 tests PASS.

- [ ] **Step 5: Register the gate in `dv_harness/gates.py`**

In `dv_harness/gates.py`'s `STAGE_GATES["IMPLEMENT"]` list, add a new tuple immediately after the existing `manual_lookup_before_edit_gate` entry:

```python
        ("manual_lookup_before_edit_gate", "manual_lookup_before_edit_gate.py", "--edit"),
        ("protocol_isolation_gate", "protocol_isolation_gate.py", "--edit"),
```

- [ ] **Step 6: Register the gate in `.dv-harness/workflow/hard_gate_registry.json`**

Open `.dv-harness/workflow/hard_gate_registry.json`. In the `gates` list, insert a new entry in alphabetical order — it belongs immediately after the `protocol_generator_binding_gate` entry and before `protocol_onboarding_gate`:

```json
  {
    "gate_id": "protocol_isolation_gate",
    "tool": "tools/verification_flow/protocol_isolation_gate.py"
  },
```

- [ ] **Step 7: Register the gate in the smoke-test list**

In `dv_harness_tests/test_hard_gate_script_smoke.py`'s `ALL_GATE_TOOL_FILES` list, insert (alphabetically, immediately after `"tools/verification_flow/protocol_generator_binding_gate.py"` if present, else in correct alphabetical position among the `protocol_*` entries):

```python
    "tools/verification_flow/protocol_isolation_gate.py",
```

- [ ] **Step 8: Write the `run_stage()`-level integration tests**

Add to `dv_harness_tests/test_engine_gates_and_routing.py`, near the existing `manual_lookup_before_edit_gate` tests (around the `_REAL_REF` constant already defined there):

```python
def test_protocol_isolation_gate_blocks_forbidden_reference_citation():
    rc, out = _run_gate_script(
        "verification_flow/protocol_isolation_gate.py", "--edit",
        {"branch": "branch_b0",
         "vip_evidence_refs": [{"path": "USB_UVM_Handoff/some_file.sv", "quote": "x"}]},
    )
    assert rc != 0 and out["status"] == "FAIL"
    assert out["reason"] == "REFERENCE_TREE_CITATION_FORBIDDEN"


def test_protocol_isolation_gate_allows_real_source_citation():
    rc, out = _run_gate_script(
        "verification_flow/protocol_isolation_gate.py", "--edit",
        {"branch": "branch_b1", "vip_evidence_refs": [_REAL_REF]},
    )
    assert rc == 0 and out["status"] == "PASS"
```

- [ ] **Step 9: Run the full suite**

Run: `python -m pytest -q`
Expected: all prior tests pass plus the 5 new standalone tests and 2 new integration tests (1046 + 7 = 1053), 0 failed.

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "Task 2: add protocol_isolation_gate.py to block reference-tree citations at IMPLEMENT"
```

---

### Task 3: Generalized profile/vip-lookup binding (B2)

**Files:**
- Modify: `.dv-harness/builder/protocol_builder_registry.json`
- Modify: `.claude/skills/CORE/protocol-router/SKILL.md`
- Create: `tools/verification_flow/protocol_profile_binding_gate.py`
- Modify: `dv_harness/gates.py` (add `STAGE_GATES["PROTOCOL_CAPABILITY"]` entry)
- Modify: `.dv-harness/workflow/hard_gate_registry.json` (append to `gates` list)
- Modify: `dv_harness_tests/test_hard_gate_script_smoke.py` (append to `ALL_GATE_TOOL_FILES`)
- Test: `dv_harness_tests/test_protocol_profile_binding_gate.py`
- Test: `dv_harness_tests/test_engine_gates_and_routing.py` (add integration tests)

**Interfaces:**
- Consumes: `.dv-harness/builder/protocol_builder_registry.json`'s existing `protocols` dict (11 keys: `pcie`, `ethernet`, `mipi-csi`, `mipi-dsi`, `canfd`, `amba4-soc`, `emmc`, `sd`, `edp`, `ucie`, `usb`), each currently having `display_name`, `skill`, `discover`, `build`.
- Produces: two new fields on every `protocols.<key>` entry — `profile_skill` (string or `null`) and `vip_lookup_skill` (string or `null`) — consumed by the new gate below and by `protocol-router`'s updated instructions. No other task consumes these.

**Real profile/vip-lookup skill mapping** (verified by listing every `*-profile`/`*-vip-lookup` `SKILL.md` under `.claude/skills/` on 2026-08-31 — re-verify this table is still accurate before implementing, since a skill directory could have moved since this plan was written):

| registry key | `profile_skill` | `vip_lookup_skill` |
|---|---|---|
| `pcie` | `"PCIe/pcie-profile"` | `null` |
| `ethernet` | `"Ethernet/ethernet-profile"` | `null` |
| `mipi-csi` | `"MIPI/csi2-profile"` | `null` |
| `mipi-dsi` | `"MIPI/dsi-profile"` | `null` |
| `canfd` | `"CAN/canfd-profile"` | `null` |
| `amba4-soc` | `"AMBA/amba-profile"` | `null` |
| `emmc` | `null` | `null` |
| `sd` | `null` | `null` |
| `edp` | `null` | `null` |
| `ucie` | `null` | `null` |
| `usb` | `"USB/usb-profile"` | `"USB/usb-vip-lookup"` |

Note: this table found that not every protocol has a profile skill (4 of 11 have neither) — the spec's assumption that `profile_skill` would be "required for every protocol" does not match the real filesystem; treat `profile_skill` as nullable, exactly like `vip_lookup_skill` (a protocol with `profile_skill: null` requires no consultation for that field, matching the same "present-but-null = not required" semantics already planned for `vip_lookup_skill`).

- [ ] **Step 1: Write the failing tests**

Create `dv_harness_tests/test_protocol_profile_binding_gate.py`:

```python
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "verification_flow" / "protocol_profile_binding_gate.py"
REGISTRY = ROOT / ".dv-harness" / "builder" / "protocol_builder_registry.json"


def _run(payload):
    tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(payload, tmp)
    tmp.close()
    try:
        r = subprocess.run(
            [sys.executable, str(SCRIPT), "--binding", tmp.name],
            cwd=str(ROOT), capture_output=True, text=True, timeout=30,
        )
        out = json.loads((r.stdout or "").strip() or "{}")
        return r.returncode, out
    finally:
        Path(tmp.name).unlink(missing_ok=True)


def test_usb_profile_and_vip_lookup_both_consulted_passes():
    rc, out = _run({"protocols": [
        {"protocol": "usb", "profile_skills_consulted": ["USB/usb-profile", "USB/usb-vip-lookup"]},
    ]})
    assert rc == 0 and out["status"] == "PASS"


def test_usb_missing_profile_skill_fails():
    rc, out = _run({"protocols": [
        {"protocol": "usb", "profile_skills_consulted": ["USB/usb-vip-lookup"]},
    ]})
    assert rc != 0 and out["status"] == "FAIL"
    assert out["reason"] == "PROFILE_SKILL_NOT_CONSULTED"
    assert out["protocol"] == "usb"
    assert "USB/usb-profile" in out["missing"]


def test_usb_missing_vip_lookup_skill_fails():
    rc, out = _run({"protocols": [
        {"protocol": "usb", "profile_skills_consulted": ["USB/usb-profile"]},
    ]})
    assert rc != 0 and out["status"] == "FAIL"
    assert "USB/usb-vip-lookup" in out["missing"]


def test_protocol_with_null_profile_skill_requires_no_consultation():
    rc, out = _run({"protocols": [
        {"protocol": "emmc", "profile_skills_consulted": []},
    ]})
    assert rc == 0 and out["status"] == "PASS"


def test_unknown_protocol_key_fails():
    rc, out = _run({"protocols": [
        {"protocol": "not-a-real-protocol", "profile_skills_consulted": []},
    ]})
    assert rc != 0 and out["status"] == "FAIL"
    assert out["reason"] == "UNKNOWN_PROTOCOL"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest dv_harness_tests/test_protocol_profile_binding_gate.py -v`
Expected: FAIL (script does not exist yet).

- [ ] **Step 3: Update `.dv-harness/builder/protocol_builder_registry.json`**

Read the current file in full first (it may have drifted since this plan was written — re-verify the 11 keys and their exact current field sets before editing). For each of the 11 entries under `protocols`, add the two fields `profile_skill` and `vip_lookup_skill` using the table above. Example for the `usb` entry (add `profile_skill`/`vip_lookup_skill` alongside its existing `display_name`/`skill`/`discover`/`build` fields, do not remove or reorder existing fields):

```json
    "usb": {
      "display_name": "USB",
      "skill": "usb-environment-builder",
      "profile_skill": "USB/usb-profile",
      "vip_lookup_skill": "USB/usb-vip-lookup",
      "discover": [ ... unchanged ... ],
      "build": [ ... unchanged ... ]
    },
```

Apply the same pattern to all 11 entries per the table (the 4 with no real profile skill get `"profile_skill": null, "vip_lookup_skill": null`; the 6 with only a profile skill get `"vip_lookup_skill": null`).

- [ ] **Step 4: Write the implementation**

Create `tools/verification_flow/protocol_profile_binding_gate.py`:

```python
#!/usr/bin/env python3
"""protocol_profile_binding_gate.py -- 2026-08-31 full-harness wiring audit
finding B2: no protocol's profile/vip-lookup skill chain was ever required
to be consulted before PROTOCOL_CAPABILITY proceeds -- protocol-router's
own SKILL.md named the routes in prose but nothing enforced an agent
actually read them. This gate cross-checks an agent's self-reported
profile_skills_consulted list against the REAL registry entry for that
protocol (harness-supplied truth, not agent-attested) -- a protocol whose
registry entry has profile_skill/vip_lookup_skill set to null requires no
consultation for that field (several real protocols genuinely have no
profile skill yet)."""
import argparse, json, pathlib, sys

REGISTRY_PATH = pathlib.Path(__file__).resolve().parents[2] / ".dv-harness" / "builder" / "protocol_builder_registry.json"


def _load_registry():
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--binding", required=True)
    a = ap.parse_args()
    d = json.loads(pathlib.Path(a.binding).read_text())
    registry = _load_registry()["protocols"]

    for p in d.get("protocols", []):
        name = p.get("protocol")
        entry = registry.get(name)
        if entry is None:
            print(json.dumps({"status": "FAIL", "reason": "UNKNOWN_PROTOCOL", "protocol": name}))
            return 2
        required = [s for s in (entry.get("profile_skill"), entry.get("vip_lookup_skill")) if s]
        consulted = set(p.get("profile_skills_consulted") or [])
        missing = [s for s in required if s not in consulted]
        if missing:
            print(json.dumps({"status": "FAIL", "reason": "PROFILE_SKILL_NOT_CONSULTED",
                               "protocol": name, "missing": missing}))
            return 3

    print(json.dumps({"status": "PASS", "protocols": len(d.get("protocols", []))}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Note the `REGISTRY_PATH` computation: `Path(__file__).resolve().parents[2]` from
`tools/verification_flow/protocol_profile_binding_gate.py` is the repo root
(`parents[0]` = `verification_flow/`, `parents[1]` = `tools/`, `parents[2]` =
repo root) — verify this resolves correctly in Step 5 rather than trusting
the arithmetic blindly.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest dv_harness_tests/test_protocol_profile_binding_gate.py -v`
Expected: all 5 tests PASS. If `REGISTRY_PATH` resolves incorrectly, fix the `parents[N]` index and re-run.

- [ ] **Step 6: Update `protocol-router`'s SKILL.md**

Edit `.claude/skills/CORE/protocol-router/SKILL.md`. After the existing "Primary routes" list, add:

```markdown
## Profile/VIP-Lookup Binding

After detecting the protocol, read `.dv-harness/builder/protocol_builder_registry.json`'s
entry for it and resolve `profile_skill` and `vip_lookup_skill` (either may
be `null` -- several protocols have no profile skill yet). For every
non-null value, actually read that skill file before proceeding, and
record every consulted skill name in the DISCOVERY/PROTOCOL_CAPABILITY
stage evidence block under `profile_skills_consulted`. This is enforced by
`protocol_profile_binding_gate` at the PROTOCOL_CAPABILITY stage -- it
cross-checks your list against the registry's real values, not your
self-report alone.
```

- [ ] **Step 7: Register the gate in `dv_harness/gates.py`**

In `STAGE_GATES["PROTOCOL_CAPABILITY"]`, add after the existing
`protocol_generator_binding_gate` entry:

```python
        ("protocol_profile_binding_gate", "protocol_profile_binding_gate.py", "--binding"),
```

- [ ] **Step 8: Register the gate in `.dv-harness/workflow/hard_gate_registry.json`**

Insert alphabetically, immediately after `protocol_onboarding_gate` and
before `protocol_profile_version_gate`:

```json
  {
    "gate_id": "protocol_profile_binding_gate",
    "tool": "tools/verification_flow/protocol_profile_binding_gate.py"
  },
```

- [ ] **Step 9: Register the gate in the smoke-test list**

In `ALL_GATE_TOOL_FILES`, insert alphabetically:

```python
    "tools/verification_flow/protocol_profile_binding_gate.py",
```

- [ ] **Step 10: Write the `run_stage()`-level integration tests**

Add to `dv_harness_tests/test_engine_gates_and_routing.py`:

```python
def test_protocol_profile_binding_gate_requires_usb_profile_and_vip_lookup():
    rc, out = _run_gate_script(
        "verification_flow/protocol_profile_binding_gate.py", "--binding",
        {"protocols": [{"protocol": "usb", "profile_skills_consulted": []}]},
    )
    assert rc != 0 and out["status"] == "FAIL" and out["reason"] == "PROFILE_SKILL_NOT_CONSULTED"


def test_protocol_profile_binding_gate_passes_when_fully_consulted():
    rc, out = _run_gate_script(
        "verification_flow/protocol_profile_binding_gate.py", "--binding",
        {"protocols": [{"protocol": "usb",
                        "profile_skills_consulted": ["USB/usb-profile", "USB/usb-vip-lookup"]}]},
    )
    assert rc == 0 and out["status"] == "PASS"
```

- [ ] **Step 11: Run the full suite**

Run: `python -m pytest -q`
Expected: all prior passing tests plus 5 + 2 = 7 new tests pass (1053 + 7 = 1060), 0 failed.

- [ ] **Step 12: Commit**

```bash
git add -A
git commit -m "Task 3: generalize profile/vip-lookup binding across all protocols"
```

---

### Task 4: Relocate persistent-relay scripts into v50

**Files:**
- Create: `tools/remote/remote_hop.py` (copied from `D:\DV\Task\DV_Agent_Harness_L5\remote_hop.py`, unchanged)
- Create: `tools/remote/remote_relay.py` (copied, unchanged — its 4-layer credential-boundary logic is NOT modified by this task)
- Create: `tools/remote/remote_exec.py` (copied, unchanged)
- Create: `tools/remote/source_identity.py` (copied, unchanged)
- Create: `dv_harness_tests/test_remote_hop.py` (there is currently no test file for `remote_hop.py` at the old location — confirm this at Step 1; if none exists, this step is skipped, not fabricated)
- Create: `dv_harness_tests/test_remote_relay.py` (copied from `D:\DV\Task\DV_Agent_Harness_L5\tests\test_remote_relay.py`, with the import-path fix below)
- Create: `dv_harness_tests/test_remote_exec.py` (copied, with the import-path fix below)
- Create: `dv_harness_tests/test_source_identity.py` (copied, with the import-path fix below)
- Delete (only after Step 6 passes): `D:\DV\Task\DV_Agent_Harness_L5\remote_hop.py`, `remote_relay.py`, `remote_exec.py`, `source_identity.py`, `D:\DV\Task\DV_Agent_Harness_L5\tests\test_remote_relay.py`, `test_remote_exec.py`, `test_source_identity.py`
- Delete (only after Step 6 passes): `D:\DV\Task\DV_Agent_Harness_L5\PACKAGE\remote_hop.py`, `remote_relay.py`, `remote_exec.py` (these mirror the OLD location; `PACKAGE` never had `source_identity.py`)
- Modify: `D:\DV\Task\DV_Agent_Harness_L5\v50\CLAUDE.md` (correct the stated file location)
- Modify: `.claude/skills/CORE/remote-linux-execution-bridge/SKILL.md` (correct the stated file location)
- Modify: `.claude/skills/CORE/remote-executor/SKILL.md` (correct the stated file location, if it names the old path)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `tools/remote/remote_exec.py`'s real, confirmed output format (`REMOTE_HOST=`/`EXIT_CODE=`/`STATUS=` lines from its `format_result()` function, confirmed unchanged by this task) — consumed by Task 5's gate.

- [ ] **Step 1: Read the 4 source files and their tests in full, confirm exact current state**

Read `D:\DV\Task\DV_Agent_Harness_L5\remote_hop.py`, `remote_relay.py`, `remote_exec.py`,
`source_identity.py`, and every file under `D:\DV\Task\DV_Agent_Harness_L5\tests\` matching
`test_remote_*.py`/`test_source_identity.py`. Confirm whether a
`test_remote_hop.py` exists (if it does, include it in this relocation
identically to the other three test files; if it does not, do not
fabricate one — `remote_hop.py`'s `Session` class is already exercised
indirectly through `test_remote_relay.py`'s `FakeSession`).

- [ ] **Step 2: Copy the 4 source files unchanged**

```bash
mkdir -p tools/remote
cp "D:\DV\Task\DV_Agent_Harness_L5\remote_hop.py" tools/remote/remote_hop.py
cp "D:\DV\Task\DV_Agent_Harness_L5\remote_relay.py" tools/remote/remote_relay.py
cp "D:\DV\Task\DV_Agent_Harness_L5\remote_exec.py" tools/remote/remote_exec.py
cp "D:\DV\Task\DV_Agent_Harness_L5\source_identity.py" tools/remote/source_identity.py
```

Diff each copied file against its source with `diff` to confirm byte-identical (0 lines of difference) before proceeding — this is the same explicit content-diff-verification method already used for the `industrial`/`PACKAGE` deliverable-tree syncs earlier in this project's history, never a self-reported "copied successfully" claim.

- [ ] **Step 3: Copy the test files and fix their `sys.path` line**

```bash
cp "D:\DV\Task\DV_Agent_Harness_L5\tests\test_remote_relay.py" dv_harness_tests/test_remote_relay.py
cp "D:\DV\Task\DV_Agent_Harness_L5\tests\test_remote_exec.py" dv_harness_tests/test_remote_exec.py
cp "D:\DV\Task\DV_Agent_Harness_L5\tests\test_source_identity.py" dv_harness_tests/test_source_identity.py
```

In each of the 3 copied test files, the original computes `ROOT = Path(__file__).resolve().parents[1]` (the repo root, since the original test lived directly under `tests/`) and then `sys.path.insert(0, str(ROOT))` before importing the module under test. At the new location (`v50/dv_harness_tests/test_remote_relay.py`), `parents[1]` now resolves to `v50/` (the `v50` repo root), but the modules moved to `v50/tools/remote/`, not `v50/` itself — so the `sys.path.insert` target must change. Apply this exact edit to all 3 files (the surrounding `ROOT = ...` line's meaning changes from "module directory" to "repo root", which is consistent with this project's other `dv_harness_tests/*.py` files' use of `ROOT`):

```python
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "remote"))
```

(replacing the original `sys.path.insert(0, str(ROOT))` line in each of the 3 files — leave every other line, including the `from remote_relay import (...)` / `from remote_exec import ...` / `from source_identity import (...)` import statements themselves, unchanged).

- [ ] **Step 4: Run the relocated tests**

Run: `python -m pytest dv_harness_tests/test_remote_relay.py dv_harness_tests/test_remote_exec.py dv_harness_tests/test_source_identity.py -v`
Expected: all tests pass with the exact same count as the original location (43 tests total across the 3 files, per this project's session history — confirm the real count by running the originals at their old location first if there is any doubt, and compare).

- [ ] **Step 5: Update documentation to the real new location**

In `D:\DV\Task\DV_Agent_Harness_L5\v50\CLAUDE.md`'s "Remote Linux Execution
(Persistent Relay)" section, change any reference to these 4 files living
"at the project root" to `tools/remote/` within the `v50` project. In
`.claude/skills/CORE/remote-linux-execution-bridge/SKILL.md`'s "Persistent
Relay" section (and `.claude/skills/CORE/remote-executor/SKILL.md` if it
names a location), make the same correction — verify the exact current
wording in each file first (read them; do not guess the phrase to
replace), and add one sentence noting `remote_execution_provenance_gate.py`
(landing in Task 5) independently verifies a real transcript rather than
trusting self-attested BUILD/VERIFY evidence.

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest -q`
Expected: 1060 + 43 (or the real confirmed count from Step 4) new tests, 0 failed.

- [ ] **Step 7: Sync to `industrial` and `PACKAGE`, verify, then delete the old copies**

Using the explicit-file-list + real-content-diff-verification method:
copy `tools/remote/remote_hop.py`, `remote_relay.py`, `remote_exec.py`,
`source_identity.py` and the 3 relocated test files from `v50` into
`D:\DV\Task\DV_Agent_Harness_L5\industrial\tools\remote\` and
`D:\DV\Task\DV_Agent_Harness_L5\PACKAGE\tools\remote\` (creating the
`tools/remote/` subdirectory in each), and the 3 test files into each
tree's `dv_harness_tests/`. Diff every copied file against its `v50`
source to confirm zero mismatches (same method used for the Round-2 plan's
23-file consolidation sync). Only after this verification passes, delete:
`D:\DV\Task\DV_Agent_Harness_L5\remote_hop.py`, `remote_relay.py`,
`remote_exec.py`, `source_identity.py`,
`D:\DV\Task\DV_Agent_Harness_L5\tests\test_remote_relay.py`,
`test_remote_exec.py`, `test_source_identity.py`,
`D:\DV\Task\DV_Agent_Harness_L5\PACKAGE\remote_hop.py`,
`PACKAGE\remote_relay.py`, `PACKAGE\remote_exec.py` — never leave two live
copies of a credential-boundary-critical script (a stale, un-updated
duplicate is a real security liability, not just clutter).

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "Task 4: relocate persistent-relay scripts from repo-external location into v50/tools/remote"
```

(Note: the deletions in Step 7 happen outside the `v50` git repo, so they
are not part of this commit — do them as a plain filesystem operation
after this commit, confirmed by the diff-verification in Step 7, not
before.)

---

### Task 5: `remote_execution_provenance_gate.py` (B4 — independent BUILD/VERIFY proof)

**Files:**
- Create: `tools/verification_flow/remote_execution_provenance_gate.py`
- Modify: `dv_harness/gates.py` (add `STAGE_GATES["BUILD"]` and `STAGE_GATES["VERIFY"]` entries)
- Modify: `.dv-harness/workflow/hard_gate_registry.json` (append to `gates` list)
- Modify: `dv_harness_tests/test_hard_gate_script_smoke.py` (append to `ALL_GATE_TOOL_FILES`)
- Test: `dv_harness_tests/test_remote_execution_provenance_gate.py`
- Test: `dv_harness_tests/test_engine_gates_and_routing.py` (add integration tests for both BUILD and VERIFY)

**Interfaces:**
- Consumes: `tools/remote/remote_exec.py`'s real `format_result()` output shape from Task 4 — exactly 3 leading lines `REMOTE_HOST=<value>`, `EXIT_CODE=<int>`, `STATUS=<PASS|FAIL>`, optionally followed by the remote command's stdout body (confirmed by reading `format_result()` directly: `lines = ['REMOTE_HOST=%s' % remote_host, 'EXIT_CODE=%s' % exit_code, 'STATUS=%s' % status]`).
- Produces: nothing consumed by later tasks (this is the last task).

- [ ] **Step 1: Write the failing tests**

Create `dv_harness_tests/test_remote_execution_provenance_gate.py`:

```python
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "verification_flow" / "remote_execution_provenance_gate.py"


def _write_transcript(tmp_path, text):
    p = tmp_path / "transcript.txt"
    p.write_text(text, encoding="utf-8")
    return str(p)


def _run(payload):
    tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(payload, tmp)
    tmp.close()
    try:
        r = subprocess.run(
            [sys.executable, str(SCRIPT), "--provenance", tmp.name],
            cwd=str(ROOT), capture_output=True, text=True, timeout=30,
        )
        out = json.loads((r.stdout or "").strip() or "{}")
        return r.returncode, out
    finally:
        Path(tmp.name).unlink(missing_ok=True)


def test_real_shaped_pass_transcript_passes(tmp_path):
    path = _write_transcript(tmp_path, "REMOTE_HOST=host-b\nEXIT_CODE=0\nSTATUS=PASS\nbuild ok\n")
    rc, out = _run({"transcript_path": path, "claimed_exit_code": 0})
    assert rc == 0 and out["status"] == "PASS"


def test_exit_code_mismatch_fails(tmp_path):
    path = _write_transcript(tmp_path, "REMOTE_HOST=host-b\nEXIT_CODE=1\nSTATUS=FAIL\nerror\n")
    rc, out = _run({"transcript_path": path, "claimed_exit_code": 0})
    assert rc != 0 and out["status"] == "FAIL"
    assert out["reason"] == "EXIT_CODE_MISMATCH"


def test_missing_transcript_file_fails(tmp_path):
    rc, out = _run({"transcript_path": str(tmp_path / "does_not_exist.txt"), "claimed_exit_code": 0})
    assert rc != 0 and out["status"] == "FAIL"
    assert out["reason"] == "TRANSCRIPT_FILE_NOT_FOUND"


def test_missing_marker_line_fails(tmp_path):
    path = _write_transcript(tmp_path, "some unrelated output\n")
    rc, out = _run({"transcript_path": path, "claimed_exit_code": 0})
    assert rc != 0 and out["status"] == "FAIL"
    assert out["reason"] == "TRANSCRIPT_MISSING_MARKERS"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest dv_harness_tests/test_remote_execution_provenance_gate.py -v`
Expected: FAIL (script does not exist yet).

- [ ] **Step 3: Write the implementation**

Create `tools/verification_flow/remote_execution_provenance_gate.py`:

```python
#!/usr/bin/env python3
"""remote_execution_provenance_gate.py -- 2026-08-31 full-harness wiring
audit finding B4: BUILD/VERIFY stage compile/simulate claims were
self-attested JSON with no independent proof a real remote execution
occurred. This gate reads a real transcript file (captured stdout of a
real tools/remote/remote_exec.py invocation) and verifies it actually
contains that script's REMOTE_HOST=/EXIT_CODE=/STATUS= structured output
(see tools/remote/remote_exec.py's format_result()), and that the claimed
exit code matches what the transcript really shows -- an agent cannot
claim BUILD/VERIFY success while the real transcript shows a nonzero exit.
"""
import argparse, json, pathlib, re, sys

_HOST_RE = re.compile(r"^REMOTE_HOST=(.*)$", re.MULTILINE)
_EXIT_RE = re.compile(r"^EXIT_CODE=(-?\d+)$", re.MULTILINE)
_STATUS_RE = re.compile(r"^STATUS=(.*)$", re.MULTILINE)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--provenance", required=True)
    a = ap.parse_args()
    d = json.loads(pathlib.Path(a.provenance).read_text())

    transcript_path = pathlib.Path(d.get("transcript_path", ""))
    if not transcript_path.is_file():
        print(json.dumps({"status": "FAIL", "reason": "TRANSCRIPT_FILE_NOT_FOUND",
                           "path": str(transcript_path)}))
        return 2

    content = transcript_path.read_text(encoding="utf-8", errors="ignore")
    host_m = _HOST_RE.search(content)
    exit_m = _EXIT_RE.search(content)
    status_m = _STATUS_RE.search(content)
    if not (host_m and host_m.group(1).strip() and exit_m and status_m):
        print(json.dumps({"status": "FAIL", "reason": "TRANSCRIPT_MISSING_MARKERS"}))
        return 3

    real_exit_code = int(exit_m.group(1))
    claimed_exit_code = d.get("claimed_exit_code")
    if real_exit_code != claimed_exit_code:
        print(json.dumps({"status": "FAIL", "reason": "EXIT_CODE_MISMATCH",
                           "claimed": claimed_exit_code, "real": real_exit_code}))
        return 4

    print(json.dumps({"status": "PASS", "remote_host": host_m.group(1).strip(),
                       "exit_code": real_exit_code}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest dv_harness_tests/test_remote_execution_provenance_gate.py -v`
Expected: all 4 tests PASS.

- [ ] **Step 5: Register the gate in `dv_harness/gates.py`**

In `STAGE_GATES["BUILD"]`, add after the existing entries:

```python
        ("remote_execution_provenance_gate", "remote_execution_provenance_gate.py", "--provenance"),
```

In `STAGE_GATES["VERIFY"]`, add the identical tuple after the existing entries (same gate script, registered under both stage keys — `run_gate()` is stateless per call, so reusing the same `gate_id`/script under two stage keys is the existing pattern this codebase already uses elsewhere; confirm no other gate_id collision exists before finalizing).

- [ ] **Step 6: Register the gate in `.dv-harness/workflow/hard_gate_registry.json`**

Insert alphabetically, immediately after `remote_control_supervisory_gate`
and before `remote_state_transition_gate`:

```json
  {
    "gate_id": "remote_execution_provenance_gate",
    "tool": "tools/verification_flow/remote_execution_provenance_gate.py"
  },
```

(one entry only, even though the gate is registered under two `STAGE_GATES`
keys — the registry tracks gate scripts, not stage bindings.)

- [ ] **Step 7: Register the gate in the smoke-test list**

In `ALL_GATE_TOOL_FILES`, insert alphabetically:

```python
    "tools/verification_flow/remote_execution_provenance_gate.py",
```

- [ ] **Step 8: Write the `run_stage()`-level integration tests**

Add to `dv_harness_tests/test_engine_gates_and_routing.py`:

```python
def test_remote_execution_provenance_gate_blocks_exit_code_mismatch_at_build(tmp_path):
    transcript = tmp_path / "build_transcript.txt"
    transcript.write_text("REMOTE_HOST=host-b\nEXIT_CODE=2\nSTATUS=FAIL\ncompile error\n", encoding="utf-8")
    rc, out = _run_gate_script(
        "verification_flow/remote_execution_provenance_gate.py", "--provenance",
        {"transcript_path": str(transcript), "claimed_exit_code": 0},
    )
    assert rc != 0 and out["status"] == "FAIL" and out["reason"] == "EXIT_CODE_MISMATCH"


def test_remote_execution_provenance_gate_passes_at_verify_with_real_transcript(tmp_path):
    transcript = tmp_path / "verify_transcript.txt"
    transcript.write_text("REMOTE_HOST=host-b\nEXIT_CODE=0\nSTATUS=PASS\nUVM_INFO ... TEST PASSED\n", encoding="utf-8")
    rc, out = _run_gate_script(
        "verification_flow/remote_execution_provenance_gate.py", "--provenance",
        {"transcript_path": str(transcript), "claimed_exit_code": 0},
    )
    assert rc == 0 and out["status"] == "PASS"
```

- [ ] **Step 9: Run the full suite**

Run: `python -m pytest -q`
Expected: all prior passing tests plus 4 + 2 = 6 new tests pass, 0 failed.

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "Task 5: add remote_execution_provenance_gate.py to BUILD and VERIFY"
```

---

## Final: Consolidation sync

After all 5 tasks land and the final whole-branch review is clean, sync
`.claude/` and every touched `dv_harness`/`tools` file (the exact list:
every file in each task's own "Files" section above, plus
`.dv-harness/workflow/hard_gate_registry.json` and
`.dv-harness/builder/protocol_builder_registry.json`, which are data files
under `.dv-harness/` rather than `.claude/`/`dv_harness`/`tools` but are
still required for the new gates to function identically in `industrial`
and `PACKAGE`) to the `industrial` and `PACKAGE` deliverable trees, using
the explicit-file-list + real-content-diff-verification approach already
established in this project's session history — never a self-reported
claim. Note that Task 4's own Step 7 already syncs the `tools/remote/`
files and their tests as part of that task; this final step covers
everything else (the 3 new gate scripts, the 3 STAGE_GATES/registry/smoke-
list files, the 2 `.dv-harness/*.json` data files, `protocol-router`'s and
the 2 relocated-scripts skills' `SKILL.md` files, and `CLAUDE.md`).
