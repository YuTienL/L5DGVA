> See MEMORY_ARCHITECTURE.md / MEMORY_SCHEMA.md for the system and record shapes these commands operate on.

# AI Agent Harness L5 — Memory Operations

Concrete, copy-pasteable commands for every real Memory operation, run
from the project root (the directory holding `.dv-harness/`).

Two real CLI surfaces exist, over two different stores — pick by which
store holds what you want:

- **`dv-harness memory status/search/show/add/promote/graph/validate/sync/
  doctor`** — the Markdown+YAML **DV-Knowledge Vault** (`memory_vault.py`).
  Human-browsable notes; the Job/Project/Engineering/Organizational mirror.
- **`python -m dv_harness.memory_cli`** — the JSON `MemoryStore` /
  `CornerCaseLibrary` (`memory.py`), i.e. the primary tier-1..5 records
  themselves, **including Working Memory, which is deliberately never
  mirrored into the Vault** (`memory_router.py`) and so is reachable only
  here.

Both accept the same filter vocabulary (`--protocol`, `--level`,
`--confidence`, `--status`, repeatable `--property KEY=VALUE`, free text);
`--tag`, `--exact` and `--linked-to` are Vault-only, because a JSON
MemoryStore record carries neither tags nor wiki-links. The Python APIs
below remain the stable layer both CLIs wrap.

## JSON MemoryStore — search / get / deprecate

```bash
# Search across all 5 tiers (JOB/PROJECT/ENGINEERING/ORGANIZATIONAL local
# tiers are all under the same MemoryStore -- Organizational's real hits
# come from the Knowledge Center, not this local search, per its own store).
python -m dv_harness.memory_cli --project-root . search \
  --protocol USB --scope branch_b0 --symptom "scoreboard mismatch" --text "split transaction"

# Structural filters (repeatable --level, exact --confidence, arbitrary
# --property KEY=VALUE read straight off the record file). A filter alone is
# a valid query -- no free text needed:
python -m dv_harness.memory_cli --project-root . search \
  --level engineering --level project --confidence HIGH --property kind=root_cause

# Deprecated/superseded records are excluded by default (status defaults to
# ACTIVE). Ask for them explicitly, or use ANY for every status at once:
python -m dv_harness.memory_cli --project-root . search --protocol USB --status DEPRECATED
python -m dv_harness.memory_cli --project-root . search --protocol USB --status ANY

# Or via the PowerShell wrapper at the repo root:
.\DV_MEMORY_SEARCH.ps1 -Protocol USB -Symptom "scoreboard mismatch" -Text "split transaction"

# Get one record by id
python -m dv_harness.memory_cli --project-root . get MEM-A1B2C3D4E5
.\DV_MEMORY_GET.ps1 -MemoryId MEM-A1B2C3D4E5

# Deprecate (status -> DEPRECATED, reason recorded, record NOT deleted)
python -m dv_harness.memory_cli --project-root . deprecate MEM-A1B2C3D4E5 --reason "VIP upgraded, sequence API changed"
```

## Corner Case Library — search / get / add / deprecate

```bash
python -m dv_harness.memory_cli --project-root . corner-case-search --protocol USB --category concurrency --text "arbitration"
python -m dv_harness.memory_cli --project-root . corner-case-get CCL-A1B2C3D4E5

# Add a raw corner case (no gate-verified resolution evidence yet -- current_evidence_required stays True)
python -m dv_harness.memory_cli --project-root . corner-case-add --record corner_case.json

# Add WITH a resolution -- goes through CornerCaseLibraryConsolidator's
# validation gate, sets current_evidence_required=False (reuse-eligible)
python -m dv_harness.memory_cli --project-root . corner-case-add --record corner_case.json --resolution resolution.json

python -m dv_harness.memory_cli --project-root . corner-case-deprecate CCL-A1B2C3D4E5 --reason "no longer applicable, RTL redesigned"
```
`corner_case.json` must include `category` (one of `CORNER_CASE_CATEGORIES`)
and `risk_tier` (`P0`-`P3`) — see MEMORY_SCHEMA.md; both raise `ValueError`
if missing/invalid. `resolution.json` fields: `test_mapping`,
`semantic_verdict`, `runtime_evidence_hash`.

## Router — routing, promotion, and confirmation (Python, no CLI wrapper yet)

```python
from pathlib import Path
from dv_harness.config import load_config
from dv_harness.memory_router import route_and_store, promote_to_organizational

root = Path(".")
cfg = load_config(root)

# Write a verified Engineering Memory finding (dedup/confirm handled automatically)
result = route_and_store(root, {
    "kind": "verified_fix", "verified": True, "protocol": "USB", "scope": "branch_b0",
    "root_cause": "scoreboard off-by-one on split transactions",
    "fix": "scoreboard.sv:142 -- compare against post-split expected length",
    "verification": {"single_sim": "PASS", "regression": "PASS", "reaudit": "CLEAN"},
}, cfg=cfg)
print(result)  # {"destination": "ENGINEERING_MEMORY", "level": "engineering", "memory_id": "MEM-...",
                #  "confirmed_existing": <True on the 2nd+ independent run>, "vault_write": {...}}

# Promote to Organizational once confirmation_count >= 2 and you have real confidence_inputs.
# confirmation_count only increments on a LATER, independent route_and_store() call that
# exact-matches the same protocol+root_cause (see engineering-memory skill) -- a fresh
# record starts at 0, so this call needs to happen after the finding has been independently
# re-derived and re-written at least twice beyond its original creation.
promotion = promote_to_organizational(root, result["memory_id"],
    confidence_inputs={"independent_sources_count": 3, "evidence_refs_verified": True,
                        "counter_evidence_count": 0, "multi_agent_consensus_count": 2},
    cfg=cfg, kind="methodology")
print(promotion)  # {"promoted": False, "reason": "INSUFFICIENT_CONFIRMATION",
                   #  "confirmation_count": 0, "required": 2} on a freshly-created record
```

`cfg={}` opts out of every cfg-driven additive behavior at once (Vault
write-through AND shared Knowledge Center push) — use it for a
deliberately local-only, no-network-activity write.

## Vault (`dv_harness.memory_vault`) — direct provider access

`dv-harness memory search` exposes every filter `provider.search()` accepts
(`--protocol`, `--project`, `--level`, `--confidence`, `--status`, `--tag`,
`--exact`, `--linked-to`, repeatable `--property KEY=VALUE`, free text), so
day-to-day retrieval needs no Python:

```bash
dv-harness memory search "scoreboard" --protocol USB --confidence HIGH --limit 5
dv-harness memory search --exact "lfps_detect_sync" --property subsystem=link_training
dv-harness memory search --linked-to MEM-A1B2C3D4E5      # notes wiki-linking to that note
```

Use the Python API below for writes/reads the CLI does not wrap
(`update`, `delete`, `list_tags`, `list_links`):

```python
from pathlib import Path
from dv_harness.config import load_config
from dv_harness.memory_vault import get_active_provider

root = Path(".")
cfg = load_config(root)
provider = get_active_provider(root, cfg)   # HybridMemoryProvider (or bare FileSystemMarkdownAdapter if obsidian_cli="disabled")

# Search the vault (keyword/tag/property/wiki-link filters, no vector index)
provider.search({"protocol": "USB", "confidence": "HIGH", "text": "scoreboard"}, limit=5)

# Read one note
provider.read("MEM-A1B2C3D4E5")

# Create a note directly (usually done for you by route_and_store()'s write-through --
# call this yourself only for a note that isn't a memory-tier promotion, e.g. a manual protocol note)
provider.create(
    {"id": "NOTE-0001", "memory_level": "engineering", "protocol": "USB",
     "status": "ACTIVE", "confidence": "MEDIUM"},
    sections={"Symptom": "- intermittent timeout on port 1"})

# Update -- a sections_patch only overwrites the named section(s)
provider.update("NOTE-0001", sections_patch={"Related Knowledge": "- [[MEM-A1B2C3D4E5]]"})

# List tags / links (forward + backlinks)
provider.list_tags()
provider.list_links("MEM-A1B2C3D4E5")

# Delete
provider.delete("NOTE-0001")
```

Every write-returning call above returns `{"ok": bool, ...}` — always
check `ok` before treating an operation as having actually happened.

## Bootstrapping the vault (first use on a new project)

```bash
python -c "from dv_harness.memory_vault import resolve_vault_path, bootstrap_vault; from dv_harness.config import load_config; from pathlib import Path; root=Path('.'); print(bootstrap_vault(resolve_vault_path(root, load_config(root))))"
```
Safe to re-run any time — additive only (`mkdir(exist_ok=True)`, never
removes/overwrites existing content).

## Confidence scoring (used before a promotion attempt)

```python
from dv_harness.inference import score_confidence, identify_gap, next_best_action
score_confidence(independent_sources_count=1, evidence_refs_verified=True,
                  counter_evidence_count=0, multi_agent_consensus_count=0)
# -> {"level": "MEDIUM", "score": 4, "capped_by_counter_evidence": False}
score_confidence(independent_sources_count=3, evidence_refs_verified=True,
                  counter_evidence_count=0, multi_agent_consensus_count=2)
# -> {"level": "HIGH", "score": 10, "capped_by_counter_evidence": False}
```

## GC lifecycle operations (Python — beyond the CLI's `deprecate` shortcut)

```python
from dv_harness.memory import MemoryStore, MemoryGC
gc = MemoryGC(MemoryStore(root))
gc.supersede("MEM-OLD0000001", superseded_by="MEM-NEW0000002", reason="fix generalized in newer record")
gc.retract("MEM-BAD0000003", reason="root cause was actually a checker bug, not a DUT bug",
           evidence={"counter_sim.log": "line 88: checker off-by-one confirmed"})
gc.flag_stale("MEM-OLD0000004", reason="VIP upgraded to v2.3, sequence API this fix depended on changed")
```

## Git-backed vault history (opt-in)

```json
// .dv-harness/config.json
"memory": { "git_enabled": true }
```
Once enabled, every `create()`/`update()`/`delete()` through
`FileSystemMarkdownAdapter` auto-`git init`s (repo-local `user.name`/
`user.email` only — never touches your global git config) and commits.
**Windows caveat**: a real full-suite regression run found that a `.git`
tree inside a directory later cleaned up with `shutil.rmtree()` (e.g. a
test's tmp-dir teardown) raises `PermissionError` on git's read-only
object files. This is why the default is `false` — enable it for a real,
persistent vault you intend to keep, not for a throwaway/test project
root.

**Real commit policy (Phase 13, 2026-09-03)**: NOT on every Working Memory
update — only on a `route_and_store()` write that lands on JOB_MEMORY
("verified Job result"), PROJECT_MEMORY ("Project Memory update"),
ENGINEERING_MEMORY (promotion), or ORGANIZATIONAL_MEMORY (approval); see
`memory_router._VAULT_WRITE_THROUGH_DESTINATIONS`. The last two are each
gated first (`engineering_admission_gate()` /
`organizational_admission_gate()`), so an unearned record is demoted to
WORKING_MEMORY and no commit is minted for it at all. Commit message is
`memory(<protocol>): <short description>` (`_build_vault_commit_message()`
— falls back to `_general` when the record carries no real protocol).
Direct `provider.create()`/`update()`/`delete()` calls (this page's Vault
examples above) keep the adapter's own generic commit message unless you
pass `commit_message=` yourself — only the router applies this policy
automatically. A real commit's SHA is written back onto the underlying
JSON record as `knowledge_commit_sha` (`memory_router._write_back_
knowledge_commit_sha()`), alongside `rtl_sha`/`tb_sha`, for cross-referencing
which vault commit captured a given finding — not for
ORGANIZATIONAL_MEMORY, which has no local JSON file to patch.

## Everyday PowerShell entry points (repo root)

```powershell
.\DV_MEMORY_SEARCH.ps1 -Protocol USB -Symptom "scoreboard mismatch"
.\DV_MEMORY_GET.ps1 -MemoryId MEM-A1B2C3D4E5
```
Both are thin wrappers around `python -m dv_harness.memory_cli` — see
their source at the repo root for the exact argument mapping.

## Checking the whole chain end to end

```
python -m pytest dv_harness_tests/test_e2e_memory_chain_usb3_lfps.py -q
python .work/e2e_usb3_lfps_demo.py
```
Both drive the same real chain against a throwaway project directory with
real git integration — a synthetic USB3 Polling.LFPS failure through memory
search, hypothesis, evidence, `score_confidence()`, root cause, verified fix,
a Job Memory write, a FAILED-attempt Job Memory write, an Engineering Memory
write, `promote_to_organizational()`, `[[WikiLink]]` forward/back traversal,
a real `knowledge_commit_sha`, and session save/restore. The pytest module is
the regression net (15 tests, one per link, run by CI and the pre-push hook);
the `.work/` script narrates the same run step by step for a human. The chain
itself lives in `dv_harness_tests/e2e_memory_chain_usb3_lfps.py`, so the two
can never describe different chains.

Only the INPUT is synthetic. The verified-fix step's real-execution half stays
`PARTIAL_NOT_PERFORMED`: a genuine PASS/FAIL verdict needs a real LSF job and
a real VCS run on the Linux server, which this LOCAL_ANALYSIS path does not
perform and does not pretend to.

## Checking these docs' own file:line citations

```
python -m dv_harness.doc_citation_check --memory-docs
python -m dv_harness.doc_citation_check docs/MEMORY_ARCHITECTURE.md
```
Every `` `module.py:<line>` `` citation in the 5 memory docs is re-derived
from the source: the checker finds the symbol the surrounding prose names,
looks up its real definition line, and exits 1 with the correct number when
the cited one has drifted (2 if a citation names no symbol that exists in the
cited file, so nothing can be checked). Run it after editing `memory.py`,
`memory_router.py` or `memory_vault.py`; `dv_harness_tests/
test_doc_citation_check.py` runs it for you in the suite.
