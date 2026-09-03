---
name: memory-retrieval
description: 依 protocol/scope/symptom/context/confidence 搜尋相似 verified memory；只提升候選假設優先級。
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# memory-retrieval
依 protocol/scope/symptom/context/confidence 搜尋相似 verified memory；只提升候選假設優先級。

核心原則：Memory is prior knowledge, not current evidence.

## Mechanics (2026-09-03, real wiring)

**Purpose**: find similar prior knowledge BEFORE forming a first hypothesis
(Engineering Memory Policy's "Before debugging" step) -- ranking input only,
never an accepted conclusion.

**Inputs**: `protocol`/`scope`/`symptom`(s)/free `text`, optionally `tag`,
`exact`, `linked_to`, or a `property` filter dict (for vault notes).

**Outputs** (two real backends, use whichever holds the tier you need):
- `dv_harness.memory.MemoryRetriever(store).search(query, limit, now)` --
  JSON-file `MemoryStore` records (working/job/project/engineering/
  organizational, plus `CornerCaseLibrary.search()` for CCL entries).
  Also reachable via CLI: `python -m dv_harness.memory_cli search
  --protocol <p> --scope <s> --symptom <s1> --symptom <s2> --text <text>`
  (`corner-case-search` for CCL), or `DV_MEMORY_SEARCH.ps1` /
  `DV_MEMORY_GET.ps1`.
- `dv_harness.memory_vault.get_active_provider(root, cfg).search(query, limit)`
  -- the human-browsable Markdown+YAML DV-Knowledge Vault note mirror (see
  `docs/MEMORY_OPERATIONS.md`); real keyword/tag/property/wiki-link
  filtering, `rg`-accelerated with a correct pure-Python fallback, no vector
  index.

**Preconditions**: none to search -- a low/no-match result is a valid,
common outcome (start from a fresh hypothesis).

**Execution Steps**:
1. Search Project Memory + Engineering Memory (+ Corner Case Library, for
   protocol/category corner cases) for the current protocol/scope/symptom.
2. Each result becomes a candidate hypothesis, ranked by relevance/its own
   stored `confidence` -- see `memory-confidence-gate` for why that stored
   confidence is never substituted for current-run confidence.
3. Validate the top candidate(s) against current RTL/VIP/log/waveform
   evidence before treating it as anything more than a lead.

**Fallback**: `rg` unavailable -> vault search silently falls back to a
full pure-Python filesystem scan (same results, slower) -- never a
correctness change.

**Evidence Requirements**: none to retrieve; validation evidence is
required before ACTING on a result (Evidence Truth Rule).

**Failure Conditions**: treating a retrieved memory's `root_cause`/`fix` as
already-confirmed for the current failure without validation is exactly the
self-confirmation loop CLAUDE.md forbids.

**Example**:
```python
from dv_harness.memory import MemoryStore, MemoryRetriever
MemoryRetriever(MemoryStore(root)).search(
    {"protocol": "USB", "symptoms": ["scoreboard mismatch"]}, limit=5)
```
