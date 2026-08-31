# Poster Gap Closing Round 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close 9 user-approved gaps between DV Agent Harness L5's poster/dashboard claims and its real, wired engine — live stats, real dashboard interactivity, coverage-trend wiring, a waiver UI, signoff-bundle completeness, a real FSDB evidence panel, HYPOTHESIS/REVIEW, memory-tier wiring, and an honest agent-roster doc.

**Architecture:** Nine tasks, executed sequentially (subagent-driven-development never parallelizes implementers). Several touch `dv_harness/dashboard.py`; ordering matters more than isolation here. See spec §5 for the recommended order, followed below.

**Tech Stack:** Python 3.10+ stdlib (`http.server`, `json`, `re`, `pathlib`), pytest. No new dependencies unless a task explicitly says otherwise.

**Spec:** `docs/superpowers/specs/2026-08-31-poster-gap-closing-round2-design.md`

## Global Constraints

- Never fabricate placeholder content where real data is absent — report absence honestly (`collect_signoff_bundle`'s existing `pattern_registry` handling is the model to follow).
- No task builds a mobile app, SSH/Telnet remote transport, multi-simulator support claims, CI/CD integration, or an FSDB waveform *viewer* — see spec §3 Non-goals.
- Every new dashboard endpoint/panel gets a real test exercising real behavior (no mocks), following `dv_harness_tests/test_dashboard_interactive.py`'s existing conventions — read that file's patterns before writing new tests in this plan.
- Comment hygiene: remove any comment that becomes stale once a task lands (e.g. dashboard.py's "not a functional selector" comments must be removed/corrected once Task 2 makes them functional).

---

## Task 1: Live stats introspection

**Files:**
- Create: `dv_harness/stats_snapshot.py`
- Modify: `dv_harness/dashboard.py` (add `/api/stats` route; replace `_iron_rules_count`'s inline regex with a call into the new module)
- Modify: `dv_harness/cli.py` (add `stats` subcommand)
- Test: `dv_harness_tests/test_stats_snapshot.py`

**Interfaces:**
- Produces: `compute_stats(root: Path) -> dict` with keys `agent_count`, `skill_count`, `iron_rule_count`, `graph_node_count`, `graph_edge_count` — Task 9 imports `agent_count`'s underlying file-listing helper.

- [ ] **Step 1: Write the failing test**

```python
# dv_harness_tests/test_stats_snapshot.py
import json
from pathlib import Path

from dv_harness.stats_snapshot import compute_stats, list_agent_files

ROOT = Path(__file__).resolve().parents[1]


def test_agent_count_matches_real_glob():
    stats = compute_stats(ROOT)
    real_count = len(list((ROOT / ".claude" / "agents").glob("*.md")))
    assert stats["agent_count"] == real_count
    assert real_count > 0


def test_skill_count_excludes_deprecated():
    stats = compute_stats(ROOT)
    all_skill_md = list((ROOT / ".claude" / "skills").rglob("SKILL.md"))
    deprecated_count = len([p for p in all_skill_md if "_deprecated" in p.parts])
    non_deprecated_count = len(all_skill_md) - deprecated_count
    assert stats["skill_count"] == non_deprecated_count
    assert deprecated_count > 0  # sanity: the _deprecated tree exists in this repo


def test_iron_rule_count_matches_regex_scan():
    import re
    text = (ROOT / ".claude" / "skills" / "CORE" / "iron-rules" / "SKILL.md").read_text(encoding="utf-8")
    expected = len(re.findall(r"(?m)^## 鐵則 \d+", text))
    stats = compute_stats(ROOT)
    assert stats["iron_rule_count"] == expected
    assert expected > 0


def test_graph_counts_match_real_json():
    graph = json.loads((ROOT / ".dv-harness" / "graph" / "main_graph.json").read_text(encoding="utf-8"))
    stats = compute_stats(ROOT)
    assert stats["graph_node_count"] == len(graph.get("nodes", []))
    assert stats["graph_edge_count"] == len(graph.get("edges", []))


def test_list_agent_files_returns_real_paths():
    files = list_agent_files(ROOT)
    assert all(p.suffix == ".md" for p in files)
    assert all(p.parent.name == "agents" for p in files)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest dv_harness_tests/test_stats_snapshot.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'dv_harness.stats_snapshot'`

- [ ] **Step 3: Implement `stats_snapshot.py`**

```python
"""dv_harness/stats_snapshot.py -- live-computed repo statistics, replacing
hand-written poster/doc numbers that drift as the repo changes. Every value
here is computed fresh from the real filesystem/graph on every call, never
cached or hardcoded.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List


def list_agent_files(root: Path) -> List[Path]:
    return sorted((root / ".claude" / "agents").glob("*.md"))


def _skill_md_files(root: Path) -> List[Path]:
    skills_dir = root / ".claude" / "skills"
    if not skills_dir.is_dir():
        return []
    return [p for p in skills_dir.rglob("SKILL.md") if "_deprecated" not in p.parts]


def _iron_rule_count(root: Path) -> int:
    path = root / ".claude" / "skills" / "CORE" / "iron-rules" / "SKILL.md"
    if not path.is_file():
        return 0
    text = path.read_text(encoding="utf-8")
    return len(re.findall(r"(?m)^## 鐵則 \d+", text))


def _graph_counts(root: Path) -> tuple[int, int]:
    path = root / ".dv-harness" / "graph" / "main_graph.json"
    if not path.is_file():
        return 0, 0
    graph = json.loads(path.read_text(encoding="utf-8"))
    return len(graph.get("nodes", [])), len(graph.get("edges", []))


def compute_stats(root: Path) -> dict:
    node_count, edge_count = _graph_counts(root)
    return {
        "agent_count": len(list_agent_files(root)),
        "skill_count": len(_skill_md_files(root)),
        "iron_rule_count": _iron_rule_count(root),
        "graph_node_count": node_count,
        "graph_edge_count": edge_count,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest dv_harness_tests/test_stats_snapshot.py -v`
Expected: PASS (5/5)

- [ ] **Step 5: Wire `dashboard.py`'s `_iron_rules_count` to reuse the new module**

Read `dashboard.py`'s current `_iron_rules_count` (around line 1035) and its one call site (`/api/state` handler). Replace the inline regex with:

```python
def _iron_rules_count(root: Path) -> int:
    from .stats_snapshot import _iron_rule_count
    return _iron_rule_count(root)
```

(Keep the function name/signature so the existing call site and `dv_harness_tests`' existing dashboard tests don't need to change — only its body now delegates.)

- [ ] **Step 6: Add the `/api/stats` dashboard route**

In `dashboard.py`'s `do_GET`, add (matching the existing `elif self.path == "/api/..."` style, alongside the other routes around line 1636-1656):

```python
            elif self.path == "/api/stats":
                self._send_json(compute_stats(project_root))
```

(Verify the exact helper name `dashboard.py` uses to send JSON responses — e.g. `self._send_json` — by reading a neighboring route handler first; use whatever the file's real convention is, don't invent a new one.) Add `from .stats_snapshot import compute_stats` to `dashboard.py`'s imports.

- [ ] **Step 7: Add the `dv-harness stats` CLI subcommand**

Read `cli.py`'s existing subcommand registration pattern (e.g. how `self-audit` or `status` is wired) and add a `stats` subcommand following the exact same pattern, calling `compute_stats(project_root)` and printing the result as JSON (matching how other read-only subcommands print their output).

- [ ] **Step 8: Run the full relevant test suite**

Run: `python -m pytest dv_harness_tests/test_stats_snapshot.py dv_harness_tests/test_dashboard_interactive.py dv_harness_tests/test_cli_remote_control.py -v`
Expected: all PASS, no regressions.

- [ ] **Step 9: Commit**

```bash
git add dv_harness/stats_snapshot.py dv_harness/dashboard.py dv_harness/cli.py dv_harness_tests/test_stats_snapshot.py
git commit -m "Task 1: add live stats introspection (agent/skill/iron-rule/graph counts)"
```

---

## Task 2: Agent-taxonomy reference doc

(Sequenced second per spec §5 — depends on Task 1's `list_agent_files`.)

**Files:**
- Create: `.claude/agents/ROSTER.md`
- Test: `dv_harness_tests/test_agent_roster_doc.py`

**Interfaces:**
- Consumes: `dv_harness.stats_snapshot.list_agent_files(root)` (Task 1).

- [ ] **Step 1: Write the failing test**

```python
# dv_harness_tests/test_agent_roster_doc.py
from pathlib import Path

from dv_harness.stats_snapshot import list_agent_files

ROOT = Path(__file__).resolve().parents[1]


def test_roster_doc_exists_and_lists_every_real_agent():
    roster = (ROOT / ".claude" / "agents" / "ROSTER.md").read_text(encoding="utf-8")
    real_agent_stems = {p.stem for p in list_agent_files(ROOT) if p.stem != "ROSTER"}
    for stem in real_agent_stems:
        assert stem in roster, f"{stem} missing from ROSTER.md"


def test_roster_doc_does_not_claim_fictional_seven_agent_taxonomy():
    roster = (ROOT / ".claude" / "agents" / "ROSTER.md").read_text(encoding="utf-8")
    for fictional in ("PM Agent", "Architect Agent", "QA&Closure", "Knowledge Agent"):
        assert fictional not in roster
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest dv_harness_tests/test_agent_roster_doc.py -v`
Expected: FAIL (`ROSTER.md` doesn't exist yet)

- [ ] **Step 3: Read every real agent file's frontmatter and write the roster**

For each file `list_agent_files(ROOT)` returns, read its YAML frontmatter `description:` field. Write `.claude/agents/ROSTER.md`:

```markdown
# Real Agent Roster (live-checkable — see dv_harness/stats_snapshot.py)

This is the canonical list of real agent profiles in this repo, for
checking any future poster/doc claim against. Do not write a taxonomy
(e.g. "7 Expert Agents: PM/Architect/.../Knowledge Agent") that doesn't
match this list — none of those names correspond to a real file here.

<!-- One entry per real .claude/agents/*.md file, name + its actual
     description: field, filled in from the real files at write time. -->
```

(The implementer fills in the actual table from the real files — do not invent role names; use each file's own `description:` frontmatter verbatim or lightly summarized.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest dv_harness_tests/test_agent_roster_doc.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add .claude/agents/ROSTER.md dv_harness_tests/test_agent_roster_doc.py
git commit -m "Task 2: add live-checkable agent roster doc"
```

---

## Task 3: Dashboard real interactivity (#8/#9/#12)

**Files:**
- Modify: `dv_harness/dashboard.py` (protocol tiles, env-mode tiles, iron-rules tile rendering; `_environment_mode_policy` gains a companion selected-mode reader)
- Modify: `dv_harness/gates.py` or wherever `execution_mode_validator`-style evidence is scanned (add an analogous `environment_mode_selection` scan, mirroring `_execution_mode()`'s exact pattern)
- Test: `dv_harness_tests/test_dashboard_interactive.py` (extend)

**Interfaces:**
- Consumes: the exact JSON-response helper name and `tile()` JS helper already in `dashboard.py` (read fresh, don't assume).

- [ ] **Step 1: Read current state fresh**

Read `dashboard.py`'s current `protocoltiles`/`envmodetiles`/`ironrulestiles` rendering block (search for those three literal strings — they may have shifted from the line numbers this plan cites) and `_execution_mode()`'s exact scanning logic (currently ~line 910-923) to use as the template for a new `_environment_mode_selected()`.

- [ ] **Step 2: Write the failing tests**

Add to `dv_harness_tests/test_dashboard_interactive.py` (read its existing fixture/harness pattern first and match it exactly — do not invent a different test harness):

```python
def test_protocol_tiles_are_clickable_elements(...):
    # Assert the rendered protocol tile HTML/JS includes a real click handler
    # or data-attribute wiring the tile to the Goal field / a protocol-scope
    # field the backend reads -- not just a static <div>.
    ...

def test_environment_mode_reflects_current_run_when_declared(...):
    # Write a fake stage result carrying an environment_mode_selection
    # evidence block (SUBSYSTEM_MODE or SYSTEM_LEVEL_MODE), call the new
    # _environment_mode_selected() scanner, assert it returns that value
    # -- mirroring test_dashboard_interactive.py's existing execution_mode
    # test pattern exactly (find and copy that test's fixture shape).
    ...

def test_iron_rules_tile_uses_tier_driven_css_class(...):
    # Assert the rendered iron-rules tile HTML includes a CSS class derived
    # from a real qualification tier value, not a flat unstyled tile.
    ...
```

(Write these against whatever the real existing test harness in that file actually looks like — read it first; the shapes above are the assertions to make, not literal fixture code, since the file's real harness pattern wasn't re-verified at plan-writing time.)

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest dv_harness_tests/test_dashboard_interactive.py -k "protocol_tiles_are_clickable or environment_mode_reflects or iron_rules_tile_uses_tier" -v`
Expected: FAIL

- [ ] **Step 4: Add `environment_mode_selection` evidence scanning**

Add `_environment_mode_selected(root)` next to `_execution_mode(root)` in `dashboard.py`, using the identical scan-all-stage-results pattern, looking for an `environment_mode_selection` evidence block with an `environment_mode` field (`SUBSYSTEM_MODE`/`SYSTEM_LEVEL_MODE`) instead of `execution_mode_validator`'s `execution_mode` field. Wire it into the `/api/state` handler's `state[...]` assembly the same way `state["execution_mode"]` is assembled.

- [ ] **Step 5: Make the protocol tiles real click targets**

Modify the `protocoltiles` rendering JS to attach a click handler per tile that sets a real field the backend already consumes (identify this field by reading how the Goal/start-run form currently submits protocol scope — do not invent a new backend field if one already exists).

- [ ] **Step 6: Make the env-mode panel reflect the real current-run selection**

Modify the `envmodetiles` rendering JS to highlight (a distinct CSS class) whichever mode key matches `s.environment_mode_selected` (new field from Step 4), falling back to the existing flat legend display when no selection has been recorded yet (never error on missing data).

- [ ] **Step 7: Add tier-driven CSS classes to the iron-rules tile**

Modify the `ironrulestiles` rendering to add a CSS class based on the real qualification tier value (read `_qualification_tiers()`'s real return shape first) — add the corresponding CSS rules in the page's `<style>` block, following its existing class-naming convention.

- [ ] **Step 8: Remove now-stale comments**

Remove/correct the "not a functional selector" / "No field anywhere tracks which mode the CURRENT run used" / "a reference legend, not this run's data" comments this task makes untrue (per Global Constraints' comment-hygiene rule).

- [ ] **Step 9: Run tests to verify they pass**

Run: `python -m pytest dv_harness_tests/test_dashboard_interactive.py -v`
Expected: all PASS

- [ ] **Step 10: Commit**

```bash
git add dv_harness/dashboard.py dv_harness_tests/test_dashboard_interactive.py
git commit -m "Task 3: real interactivity for protocol/env-mode/iron-rules dashboard tiles"
```

---

## Task 4: Waiver authoring interface

**Files:**
- Modify: `dv_harness/dashboard.py` (new `POST /api/waiver` route, new dashboard form section)
- Create: `dv_harness/waiver_store.py` (append/read helpers for `.dv-harness/waivers/waivers.json`)
- Modify: whichever waiver-consuming gate scripts need an adapter to read the shared store (confirm exact assembly point per spec §8 open question before finalizing this step)
- Test: `dv_harness_tests/test_waiver_store.py`, extend `dv_harness_tests/test_dashboard_interactive.py`

- [ ] **Step 1: Read all six waiver-consuming gate scripts fresh**

`tools/verification_flow/waiver_scope_consistency_gate.py`, `waiver_revision_freshness_gate.py`, `waiver_revalidation_gate.py`, `coverage_hole_regeneration_gate.py`, `coverage_hole_to_test_generation_gate.py`, `sequence_coverage_closure_gate.py` — confirm their exact current expected input shapes (Round 1 research already captured these; re-verify field names haven't shifted).

- [ ] **Step 2: Write the failing test for the store**

```python
# dv_harness_tests/test_waiver_store.py
import json
from pathlib import Path

from dv_harness.waiver_store import append_waiver, read_waivers


def test_append_and_read_roundtrip(tmp_path):
    record = {
        "gate_id": "coverage_hole_regeneration_gate",
        "item_id": "cov-hole-42",
        "approved": True,
        "evidence": "manually reviewed against spec section 4.2",
    }
    append_waiver(tmp_path, record)
    waivers = read_waivers(tmp_path)
    assert len(waivers) == 1
    assert waivers[0]["gate_id"] == "coverage_hole_regeneration_gate"
    assert waivers[0]["item_id"] == "cov-hole-42"
    assert "recorded_at" in waivers[0]


def test_append_requires_approved_and_evidence(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        append_waiver(tmp_path, {"gate_id": "x", "item_id": "y"})  # missing approved/evidence
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest dv_harness_tests/test_waiver_store.py -v`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 4: Implement `waiver_store.py`**

```python
"""dv_harness/waiver_store.py -- shared, human-authored waiver records at
.dv-harness/waivers/waivers.json, readable by the six waiver-consuming
gate scripts under tools/verification_flow/. Distinct from an AI agent's
own fenced dv-harness-evidence waiver blocks -- this is the human-facing
persistence layer a dashboard form writes to."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List

REQUIRED_FIELDS = ("gate_id", "item_id", "approved", "evidence")


def _store_path(root: Path) -> Path:
    return root / ".dv-harness" / "waivers" / "waivers.json"


def read_waivers(root: Path) -> List[Dict[str, Any]]:
    path = _store_path(root)
    if not path.is_file():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def append_waiver(root: Path, record: Dict[str, Any]) -> Dict[str, Any]:
    missing = [f for f in REQUIRED_FIELDS if f not in record or record[f] in (None, "")]
    if missing:
        raise ValueError(f"waiver record missing required fields: {missing}")
    record = dict(record)
    record["recorded_at"] = time.time()
    path = _store_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    waivers = read_waivers(root)
    waivers.append(record)
    path.write_text(json.dumps(waivers, indent=2), encoding="utf-8")
    return record
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest dv_harness_tests/test_waiver_store.py -v`
Expected: PASS (2/2)

- [ ] **Step 6: Add the `/api/waiver` POST route and dashboard form**

Read `dashboard.py`'s existing `do_POST` handlers (e.g. `/api/upload` or `/api/session/save`) for the exact body-parsing convention, and add:

```python
            elif self.path == "/api/waiver":
                self._handle_waiver_submit(project_root)
```

with a handler method following the same body-read/JSON-parse/response convention as a neighboring POST handler, calling `waiver_store.append_waiver(project_root, body)` and catching `ValueError` into a 400-style JSON error response (match the existing error-response convention in the file). Add a form section to the dashboard HTML (gate_id select populated from the six known gate ids, item_id text input, evidence textarea, submit button posting to `/api/waiver`).

- [ ] **Step 7: Wire the shared store into gate consumption (adapter)**

Based on Step 1's findings, add the minimal adapter so a gate's own `--waivers`/`--holes` argument can be populated from `waiver_store.read_waivers()`'s content, without changing any gate script's own pass/fail logic. If Step 1 finds this is assembled at agent-evidence-writing time (not a fixed harness code path), document that finding in the commit message and scope this step down to just exposing `read_waivers()` as the source of truth an agent/skill should reference — do not force a code-level integration point that doesn't exist.

- [ ] **Step 8: Test the new POST route**

Extend `dv_harness_tests/test_dashboard_interactive.py` with a test posting a valid waiver body to `/api/waiver` and asserting `waiver_store.read_waivers()` reflects it, plus a test posting an invalid (missing evidence) body and asserting a 400-style response.

- [ ] **Step 9: Run tests to verify they pass**

Run: `python -m pytest dv_harness_tests/test_waiver_store.py dv_harness_tests/test_dashboard_interactive.py -v`
Expected: all PASS

- [ ] **Step 10: Commit**

```bash
git add dv_harness/waiver_store.py dv_harness/dashboard.py dv_harness_tests/test_waiver_store.py dv_harness_tests/test_dashboard_interactive.py
git commit -m "Task 4: add human-facing waiver authoring interface"
```

---

## Task 5: FSDB structured evidence panel (#11)

**Files:**
- Modify: `dv_harness/fsdb_report.py` (real `parse_fsdbreport_output` implementation)
- Modify: `dv_harness/dashboard.py` (new `GET /api/fsdb-report` route + panel)
- Test: extend `dv_harness_tests/test_fsdb_report.py`

- [ ] **Step 1: Read existing fixtures and the confirmed-real usage note**

Read `dv_harness_tests/test_fsdb_report.py` fully for existing fixture format. Read `.claude/skills/CORE/dv-workflow/SKILL.md`'s 2026-08-29 confirmed-drift entry (lines ~241-255) for the real confirmed invocation: `fsdbreport f.fsdb -period <T> -level 1 -csv`.

- [ ] **Step 2: Write the failing test**

```python
def test_parse_fsdbreport_csv_output_produces_structured_records():
    # Use a real-shaped CSV sample matching the confirmed -csv output format
    # from dv-workflow/SKILL.md's 2026-08-29 note (build the fixture from
    # that note's actual documented shape, not a guess) as input to
    # parse_fsdbreport_output(); assert the result has parsed=True and a
    # list of {signal, timestamp, value} (or the real equivalent field
    # names the CSV format actually uses) records, non-empty.
    ...


def test_parse_fsdbreport_output_still_handles_unparseable_input_honestly():
    from dv_harness.fsdb_report import parse_fsdbreport_output
    result = parse_fsdbreport_output("not csv at all, garbage text")
    assert result["parsed"] is False
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest dv_harness_tests/test_fsdb_report.py -k parse_fsdbreport_csv -v`
Expected: FAIL

- [ ] **Step 4: Implement real CSV parsing**

Replace `parse_fsdbreport_output`'s stub body with real `csv` module parsing of the `-csv` output shape, returning `{"parsed": True, "records": [...]}` on success and the existing honest `{"parsed": False, ...}` shape when the input doesn't match the expected CSV structure (never raise on malformed input — degrade to the honest unparsed result).

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest dv_harness_tests/test_fsdb_report.py -v`
Expected: all PASS

- [ ] **Step 6: Add the dashboard panel**

Add `GET /api/fsdb-report?path=<fsdb_path>&period=<T>&hier=<scope>` to `dashboard.py`'s `do_GET`, calling `run_fsdbreport()` then `parse_fsdbreport_output()`, returning the structured records as JSON. Add a panel to the dashboard HTML: a path/period/hierarchy input form plus a results table with a client-side signal-name filter (matching the existing table-rendering convention used elsewhere in the file, e.g. the coverage-holes table).

- [ ] **Step 7: Test the new route**

Extend the dashboard test file with a test that stubs/fakes `run_fsdbreport` (real subprocess execution against a real `fsdbreport` binary is out of scope for automated tests — this repo has no such binary available; mock only at this one external-process boundary, not the parsing logic) and asserts the route returns real parsed records for valid CSV input.

- [ ] **Step 8: Run tests to verify they pass**

Run: `python -m pytest dv_harness_tests/test_fsdb_report.py dv_harness_tests/test_dashboard_interactive.py -v`
Expected: all PASS

- [ ] **Step 9: Commit**

```bash
git add dv_harness/fsdb_report.py dv_harness/dashboard.py dv_harness_tests/test_fsdb_report.py
git commit -m "Task 5: real FSDB CSV-evidence parsing + dashboard panel"
```

---

## Task 6: Coverage trend real data

**Files:**
- Modify: `dv_harness/engine.py` (new auto-write call site in `run_stage()`)
- Test: extend `dv_harness_tests/test_engine_gates_and_routing.py`

- [ ] **Step 1: Read `_promote_experience_knowledge` fully and the COVERAGE_CLOSURE gate list**

Read `engine.py`'s `_promote_experience_knowledge` end-to-end (its full body, not just the previously-seen prefix) to get its exact calling convention (what evidence_blocks shape it reads, how it's invoked from `run_stage()`). Read `gates.py`'s `STAGE_GATES['COVERAGE_CLOSURE']` list for the exact gate id(s) that report a coverage percent in their evidence.

- [ ] **Step 2: Write the failing test**

```python
def test_coverage_closure_pass_appends_a_real_history_sample(tmp_path, monkeypatch):
    # Build a minimal harness fixture (mirroring this test file's existing
    # fixture pattern) where a COVERAGE_CLOSURE stage's agent response
    # carries a real coverage-percent evidence block and passes its gate.
    # Run run_stage() for that stage. Assert
    # .dv-harness/coverage/history.json now has one more entry than before,
    # with a percent matching the evidence block's reported value.
    ...
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest dv_harness_tests/test_engine_gates_and_routing.py -k coverage_closure_pass_appends -v`
Expected: FAIL

- [ ] **Step 4: Add the auto-write call site**

In `engine.py`'s `run_stage()`, following the exact pattern `_promote_experience_knowledge` uses (a helper method, called from the same PASS-verdict branch, gated on the stage's `STAGE_GATES` including the relevant coverage-closure gate id), add a call that extracts the real coverage percent from the passing evidence block and calls `dashboard.append_coverage_history_sample(root, percent)` (import from `dashboard.py`, or relocate the function to a lower-level module both `engine.py` and `dashboard.py` can import without a circular-import issue — check for that before deciding which module owns it).

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest dv_harness_tests/test_engine_gates_and_routing.py -v`
Expected: all PASS, no regressions

- [ ] **Step 6: Commit**

```bash
git add dv_harness/engine.py dv_harness_tests/test_engine_gates_and_routing.py
git commit -m "Task 6: wire real coverage-trend history writes into COVERAGE_CLOSURE"
```

---

## Task 7: Signoff bundle completeness

**Files:**
- Modify: `dv_harness/signoff_export.py`
- Test: extend `dv_harness_tests/test_signoff_export.py`

- [ ] **Step 1: Locate the real generated-environment and regression-manifest sources**

Read `dv_harness/uvm_generator/protocol_env_generator.py`'s `ProtocolEnvGenerator` for its exact output directory structure and check `examples/generated_*_uvm_env/` for a real on-disk example. Read `regression_list_manager.py` and `pattern_registry_generator.py` for the real regression-list/pattern-registry artifact path(s).

- [ ] **Step 2: Write the failing tests**

```python
def test_signoff_bundle_includes_tb_source_when_present(tmp_path):
    # Create a fake generated-environment tb/ tree under the fixture root
    # (matching ProtocolEnvGenerator's real subdirectory shape found in
    # Step 1), run collect_signoff_bundle(), assert the bundle output
    # includes those tb/ files.
    ...

def test_signoff_bundle_honestly_reports_missing_tb_source(tmp_path):
    # No tb/ tree present -- assert the bundle result explicitly reports
    # its absence (matching the existing pattern_registry "reported
    # absent" convention), never fabricates placeholder content.
    ...

def test_signoff_bundle_includes_regression_manifest_when_present(tmp_path):
    ...
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest dv_harness_tests/test_signoff_export.py -k "tb_source or regression_manifest" -v`
Expected: FAIL

- [ ] **Step 4: Add the two new candidates to `collect_signoff_bundle`**

Following the exact pattern the existing `BLACKBOARD_CANDIDATES` list and whole-dir-copy logic already use, add a TB-source candidate (copy the real `tb/` tree when found, report absence honestly when not) and a regression-manifest candidate (same treatment) from Step 1's confirmed real paths.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest dv_harness_tests/test_signoff_export.py -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add dv_harness/signoff_export.py dv_harness_tests/test_signoff_export.py
git commit -m "Task 7: add UVM testbench source and regression manifest to signoff bundle"
```

---

## Task 8: HYPOTHESIS real implementation, REVIEW differentiation

**Files:**
- Modify: `dv_harness/remote_control.py`
- Modify: `tools/verification_flow/remote_state_transition_gate.py`
- Test: extend `dv_harness_tests/test_remote_control.py`

- [ ] **Step 1: Read the exact current state**

Read `remote_control.py`'s `ALLOWED_COMMANDS`, `validate_and_transition()`, and however `REVIEW`/`STATUS` currently resolve (confirmed identical, no-ControlPlane-effect, read-only). Read `remote_state_transition_gate.py`'s exact legal-transition table structure.

- [ ] **Step 2: Write the failing tests**

```python
def test_hypothesis_is_now_an_allowed_command():
    from dv_harness.remote_control import ALLOWED_COMMANDS
    assert "HYPOTHESIS" in ALLOWED_COMMANDS


def test_hypothesis_scores_a_real_confidence_value(tmp_path):
    # Call validate_and_transition("HYPOTHESIS", ...) with a fixture
    # evidence_snapshot carrying independent_sources_count/counter_evidence
    # etc.; assert the result includes a confidence score computed by
    # inference.score_confidence() (not a hardcoded/self-reported value) --
    # e.g. by constructing two fixtures that should score differently and
    # asserting the scores differ accordingly (a "crux" style test, matching
    # this project's own ReAct-loop test conventions).
    ...


def test_review_is_no_longer_identical_to_status(tmp_path):
    # Call both REVIEW and STATUS against the same fixture state; assert
    # REVIEW's output includes evidence blocks/confidence/gate-verdict
    # detail that STATUS's output does not.
    ...
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest dv_harness_tests/test_remote_control.py -k "hypothesis or review_is_no_longer" -v`
Expected: FAIL

- [ ] **Step 4: Add `HYPOTHESIS` to `ALLOWED_COMMANDS` and the transition gate**

Add `"HYPOTHESIS"` to `ALLOWED_COMMANDS` in `remote_control.py`. Add a corresponding row to `remote_state_transition_gate.py`'s legal-transition table (read-only effect, same state -> same state, matching STATUS/REVIEW's existing treatment there).

- [ ] **Step 5: Implement HYPOTHESIS's real effect**

In `remote_control.py`'s command-dispatch logic, add a `HYPOTHESIS` branch that calls `inference.score_confidence()`/`identify_gap()`/`next_best_action()` (import from `dv_harness.inference`, exact signatures confirmed real/wired: `score_confidence(independent_sources_count, evidence_refs_verified, counter_evidence_count, multi_agent_consensus_count)`) against the current stage's evidence snapshot, returning/persisting the scored hypothesis result in the same response shape STATUS/REVIEW already use, extended with the new fields.

- [ ] **Step 6: Implement REVIEW's differentiated logic**

Add a distinct branch for `REVIEW` (currently falls through identically to STATUS) that surfaces the current stage's real evidence blocks, its recomputed confidence score, and its gate verdict — read-only, no state transition, but genuinely different response content from STATUS.

- [ ] **Step 7: Run tests to verify they pass**

Run: `python -m pytest dv_harness_tests/test_remote_control.py -v`
Expected: all PASS

- [ ] **Step 8: Commit**

```bash
git add dv_harness/remote_control.py tools/verification_flow/remote_state_transition_gate.py dv_harness_tests/test_remote_control.py
git commit -m "Task 8: implement HYPOTHESIS via inference engine, differentiate REVIEW from STATUS"
```

---

## Task 9: Memory-tier wiring

**Files:**
- Modify: `dv_harness/engine.py`
- Test: extend `dv_harness_tests/test_memory_tier_completion.py` (or wherever engine-level memory wiring tests belong — check both that file and `test_engine_gates_and_routing.py`)

- [ ] **Step 1: Read `_promote_experience_knowledge` fully (past line ~365) and the LSF reconcile path**

Get its complete body (this plan's research pass didn't confirm whether it calls `route_and_store` directly or an older path — resolve this before writing new code). Read `lsf_client.py`/`cli.py`'s `lsf-reconcile` real code path for where a Job-tier write would naturally hook in.

- [ ] **Step 2: Write the failing tests**

```python
def test_lsf_reconcile_writes_a_job_tier_memory_record(tmp_path):
    # Run the real lsf-reconcile path against a fixture job state, assert
    # a JobMemoryStore record now exists reflecting that job's outcome.
    ...


def test_project_model_pass_writes_a_project_tier_memory_record(tmp_path):
    # Run run_stage() for PROJECT_MODEL with a fixture PASS response,
    # assert a ProjectMemoryStore record now exists.
    ...


def test_run_stage_retrieves_relevant_memory_into_the_prompt(tmp_path):
    # Seed a memory record relevant to a fixture goal, run run_stage(),
    # assert MemoryRetriever.search() was called and its result influenced
    # the built prompt (e.g. assert a marker string from the seeded record
    # appears in the prompt passed to the adapter).
    ...


def test_run_stage_with_no_relevant_memory_is_a_pure_no_op(tmp_path):
    # No seeded memory -- assert run_stage()'s prompt is unchanged from
    # today's behavior (no error, no spurious content).
    ...
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest dv_harness_tests/test_memory_tier_completion.py dv_harness_tests/test_engine_gates_and_routing.py -k "job_tier_memory or project_tier_memory or retrieves_relevant_memory or pure_no_op" -v`
Expected: FAIL

- [ ] **Step 4: Add the Job-tier write call site**

Following `_promote_experience_knowledge`'s exact pattern (confirmed in Step 1), add an analogous call in the LSF reconcile path building a `job_result`/`job_failure` kind record and calling `memory_router.route_and_store()`.

- [ ] **Step 5: Add the Project-tier write call site**

Add an analogous call in `run_stage()`'s PASS branch for the PROJECT_MODEL stage (or whichever stage's `STAGE_GATES` correspond to project-level facts, confirmed in Step 1), building a `project_fact`/`project_topology` kind record.

- [ ] **Step 6: Add the `MemoryRetriever.search()` read call**

In `run_stage()`, near the existing `bb_snapshot = self.blackboard.snapshot(...)` call, add a `MemoryRetriever(MemoryStore(root)).search(query)` call and thread its results into `build_stage_prompt()`'s existing additive-kwargs mechanism (matching how `constraints`/`correction_note`/`human_approval` are already threaded in) — must be a no-op (empty results, unchanged prompt) when nothing relevant is found.

- [ ] **Step 7: Run tests to verify they pass**

Run: `python -m pytest dv_harness_tests/test_memory_tier_completion.py dv_harness_tests/test_engine_gates_and_routing.py -v`
Expected: all PASS, no regressions

- [ ] **Step 8: Commit**

```bash
git add dv_harness/engine.py dv_harness_tests/test_memory_tier_completion.py
git commit -m "Task 9: wire Job/Project-tier memory writes and MemoryRetriever reads into run_stage()"
```

---

## Final: Consolidation sync

After all 9 tasks land and the final whole-branch review is clean, sync `.claude/` and the touched `dv_harness`/`tools` files to `industrial` and `PACKAGE`, using the corrected explicit-file-list + real-content-diff-verification approach from the prior plan's Task 7 redo (see `docs/superpowers/plans/2026-08-31-protocol-generalization-gap-closing.md`'s ledger for the exact method) — never a self-reported claim.
