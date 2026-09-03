> See START_HERE.md for the canonical entry point and current mechanism overview; this page covers the Engineering Memory system specifically. See also KNOWLEDGE_CENTER_GUIDE.md (the separate, cross-user shared store) and USAGE_MULTI_USER_SAFETY.md.

# AI Agent Harness L5 — Memory Architecture

This is the real, wired architecture of the 5-tier Memory system as of
2026-09-03 (Obsidian+Git/Markdown Hybrid Engineering Memory integration).
Every module/class/function named below is real code, not aspirational —
file:line references are given so any claim here can be checked against
the source directly. Those line numbers rot every time a cited module is
edited, so they are no longer trusted on sight: `python -m
dv_harness.doc_citation_check --memory-docs` re-derives each cited symbol's
real definition line and exits non-zero on drift, and
`dv_harness_tests/test_doc_citation_check.py` runs it over all 5 memory docs
as part of the suite. Function/file names are the durable half of a citation;
the number is the checked half.

## Why two memory systems exist, and how they relate

There are THREE distinct stores in this harness that are easy to conflate.
Do not conflate them:

| Store | Scope | Format | Where |
|---|---|---|---|
| **`.dv-harness/memory/`** (`dv_harness/memory.py`) | per-project, 5 tiers | JSON files, system of record | local project dir |
| **DV-Knowledge Vault** (`dv_harness/memory_vault.py`) | per-project, human-browsable mirror of Engineering/Organizational promotions | Markdown + YAML frontmatter | `.dv-harness/vault/` (configurable) |
| **Knowledge Center** (`tools/knowledge_center/broker.py`) | cross-user, cross-project shared | plain JSON on a remote Linux server | `/home/svcacct/AI/DB` |

The **JSON MemoryStore is the system of record** for every gate, router,
and skill in this codebase — nothing was replaced by this workstream. The
**Vault is an ADDITIVE, write-through mirror**: on an ENGINEERING_MEMORY or
ORGANIZATIONAL_MEMORY promotion, `memory_router.py` also writes a
Markdown+YAML note so a human can browse/search/link engineering knowledge
in a normal text editor or (optionally, opportunistically) real Obsidian —
see OBSIDIAN_INTEGRATION.md. The **Knowledge Center is a completely
different, pre-existing thing**: a cross-user shared server-side store,
not git/markdown, not this workstream's subject — see
KNOWLEDGE_CENTER_GUIDE.md. A promotion to ENGINEERING_MEMORY or
CORNER_CASE_LIBRARY can push to BOTH the Vault and the Knowledge Center
independently; neither depends on the other.

```
                      route_and_store(root, record, cfg)
                                  |
                        route_memory(record) -> destination
                                  |
        +----------------+----------------+-----------------+------------------+
        |                |                |                 |                  |
   WORKING_MEMORY   JOB/PROJECT_MEMORY  ENGINEERING_MEMORY  ORGANIZATIONAL_MEMORY  BLACKBOARD /
   (fallback for     (tier-scoped        |                   |                  CLAUDE_PROJECT_MEMORY /
   unmatched kind,   JSON stores)        |                   |                  CORNER_CASE_LIBRARY / REJECT
   react_reasoning_                      |                   |
   step)                                 v                   v
                              .dv-harness/memory/     OrganizationalMemoryStore
                              engineering/*.json      (no local file store --
                              (dedup+confirm via       Knowledge Center IS
                              _add_or_confirm_          its backing store)
                              engineering())
                                  |                        |
                                  +-----------+------------+
                                              |
                                   _maybe_write_vault_note()
                                   (best-effort, never blocks
                                    the local write)
                                              |
                                              v
                                 HybridMemoryProvider
                                 (Obsidian per-call if READY,
                                  else FileSystemMarkdownAdapter)
                                              |
                                              v
                                  .dv-harness/vault/06_Agent_Memory/*/*.md
```

## The 5 tiers (`dv_harness/memory.py`)

`MEMORY_LEVELS = ["working", "job", "project", "engineering", "organizational"]`
(`dv_harness/memory.py:10`). Each tier's records live at
`.dv-harness/memory/<level>/<memory_id>.json`, with a flat
`.dv-harness/memory/index.json` summary across all tiers.

| Tier | Class | Real trigger (routing rule) | Verified required? |
|---|---|---|---|
| Working | `WorkingMemoryStore` | fallback for any unmatched `kind`; explicit for `kind="react_reasoning_step"` | no |
| Job | `JobMemoryStore` | `kind` in `job_result`/`job_failure`/`job_rerun` | no |
| Project | `ProjectMemoryStore` | `kind` in `project_fact`/`project_topology`/`tool_flow`/`known_issue` | **yes** |
| Engineering | plain `MemoryStore.add("engineering", ...)` (no dedicated tier class — see `memory_router.py`'s comment on why) | `kind` in `root_cause`/`verified_fix`/`debug_lesson` | **yes** |
| Organizational | `OrganizationalMemoryStore` (no local JSON file — see below) | `kind` in `cross_project_lesson`/`methodology`/`best_practice`, **and only ever reached via `promote_to_organizational()`** | **yes**, plus 3-gate promotion (see below) |

Routing itself is `dv_harness.memory_router.route_memory(record) -> str`
(`memory_router.py:571`) — a pure function, kind/verified/scope in,
destination string out. `route_and_store(root, record, cfg)`
(`memory_router.py:91`) is the real entry point: routes, persists, and
(for shareable destinations) pushes to the Knowledge Center and/or Vault.

A `kind` of `credential`/`password`/`token`/`secret` is hard-`REJECT`ed
before any write happens — see the Engineering Memory Policy's "Never"
rules in `CLAUDE.md`.

### The write-time guard: secrets and large artifacts

`route_memory()`'s `REJECT` above stops a record that **is** a credential. It
cannot see a secret-shaped string embedded in a legitimate record's free-text
field, and it says nothing about artifact size. Both of those are enforced one
layer down, inside `memory._guard_record_before_write()`, which every
`MemoryStore.add()` and `CornerCaseLibrary.add()` call passes through before
anything reaches disk — including `WORKING_MEMORY`, the tier that is
deliberately never mirrored into the Vault
(`memory_router._VAULT_WRITE_THROUGH_DESTINATIONS`) and therefore has no other
scanner.

1. **Secret redaction** — `memory_security.redact_record()` walks the record
   recursively (nested dicts, lists of dicts) and redacts every match of the
   pattern registry in `memory_security.SECRET_PATTERNS`, replacing only the
   secret VALUE with `***REDACTED-<TYPE>***` and keeping the surrounding key
   name legible. The record is stamped `secrets_redacted: true` /
   `secrets_redacted_types: [...]`. Structural/identity keys
   (`_RECORD_SKIP_KEYS`, notably `memory_id`/`ccl_id`) are never rewritten.
   The Markdown mirror runs the same detector independently via
   `memory_vault.FileSystemMarkdownAdapter.create()`/`update()`.
2. **Large-artifact policy** (`memory_artifact_policy.py`) — raw binary or
   waveform-dump content (a NUL byte; `$enddefinitions` + `$dumpvars`) raises
   `EmbeddedArtifactError` and nothing is written. Oversized free text
   (>`MAX_RECORD_FIELD_CHARS` / >`MAX_RECORD_FIELD_LINES`) is bounded to head
   **and tail** — a sim.log's UVM epilogue lives at the end — with an explicit
   in-band marker, and the affected fields are recorded as
   `large_artifact_truncated`. `memory_doctor.check_large_files()` is the
   post-hoc half of the same policy, scanning the Vault tree on disk for
   artifacts that arrived by some route other than a memory write.

Redaction runs **before** truncation: truncating first can split a multi-line
secret (an SSH PEM block) so its BEGIN/END-anchored pattern no longer matches.

Artifacts are referenced, never embedded.
`memory_artifact_policy.build_evidence_reference()` is the one builder for the
`evidence: {sim_log, fsdb, coverage, lsf_job}` block (plus `run_dir`); it takes
paths and ids only and raises on anything multi-line or content-sized. A key
with no real source is omitted rather than written as `null` — `coverage` is
omitted today because no code path in this repo records a per-job coverage
database path.

### The admission boundary: (Working/Project) → Engineering

`route_memory()`'s `verified` column above is a caller-supplied boolean, so
for the Engineering tier it is a necessary but **not** sufficient condition.
`memory_router.engineering_admission_gate(record)` runs on every
`ENGINEERING_MEMORY` write and requires all three of:

1. **Evidence** — non-empty `evidence`, OR a `verification` block in one of
   the two gate-validated shapes below (the SAME
   `_verification_is_gate_validated()` the organizational gate uses).
2. **Confidence** — `confidence` in `HIGH`/`CONFIRMED`
   (`ENGINEERING_ADMISSION_CONFIDENCE_LEVELS`), or, equivalently, a
   gate-validated `verification` block (independently gate-script-verified
   evidence rather than a self-declared label).
3. **Reusable** — `reusable` not explicitly `False`, and at least one of
   `root_cause`/`fix`/`lesson` (`ENGINEERING_REUSABLE_CLAIM_FIELDS`) present.

A record failing any of them is **demoted to Working Memory**, not dropped
and not raised on: it is written to the working tier carrying
`engineering_admission_rejected: [<reason codes>]`, and `route_and_store()`
returns `{"destination": "WORKING_MEMORY", "requested_destination":
"ENGINEERING_MEMORY", "engineering_admission": {...}}`. That is CLAUDE.md's
Engineering Memory Policy ("an unverified hypothesis … belongs in Working
Memory until it clears verification") as enforced code rather than trusted
prose. Reason codes: `NO_EVIDENCE`, `CONFIDENCE_BELOW_HIGH`,
`EXPLICITLY_NOT_REUSABLE`, `NO_REUSABLE_CLAIM`.

### index.json integrity

`index.json` is a derived search projection of the per-tier record files
(`MemoryStore._index_row()`), and the record files are the system of record.
`MemoryRetriever.search()` iterates the index; `MemoryStore.get()` reads the
file — so a record file with no index row is silently unsearchable while
still looking healthy. `MemoryStore.add()` holds a cross-process lock
(`.dv-harness/memory/.index.lock`, atomic `os.mkdir`) around the index's
read-modify-write and replaces it atomically, so concurrent harness
processes cannot lose each other's rows. `MemoryStore.index_integrity()`
reports drift (surfaced by `dv-harness memory doctor`'s `memory_store_index`
check) and `MemoryStore.reindex()` repairs it from the files:

```
python -m dv_harness.memory_cli --project-root . index-check
python -m dv_harness.memory_cli --project-root . reindex
```

### Organizational Memory has no local file store, by design

Unlike the other 4 tiers, `OrganizationalMemoryStore.add()` writes straight
to the shared Knowledge Center (`memory.py:783-789`) — there is no
`.dv-harness/memory/organizational/*.json`. The Vault write-through still
happens locally (a human-browsable copy), but the tier's actual backing
store IS the cross-user Knowledge Center, because organizational knowledge
is by definition meant to be reused across projects, not kept siloed in
the one project that happened to promote it.

### The promotion boundary: Engineering → Organizational

`memory_router.promote_to_organizational(root, memory_id, confidence_inputs,
cfg, kind)` (`memory_router.py:445`) is the ONLY code path allowed to move
a record across this boundary. Three independent, all-required gates:

1. **Qualitative**: `_verification_is_gate_validated(mem)` recognizes
   exactly two real verification shapes this codebase's write paths
   produce (`finding_consolidation_shape` from
   `MemoryConsolidator.from_closed_finding()`, or `re_audit_gate_shape`
   from `engine.py`'s `_promote_verified_fix_knowledge()`) — see
   MEMORY_SCHEMA.md for both shapes' exact fields.
2. **Quantitative**: `inference.score_confidence(independent_sources_count,
   evidence_refs_verified, counter_evidence_count,
   multi_agent_consensus_count)` must return `level == "HIGH"`.
3. **Repeated confirmation**: `confirmation_count >=
   ORGANIZATIONAL_MIN_CONFIRMATIONS` (2, hardcoded — not a per-project
   config knob). `confirmation_count` is incremented by
   `_add_or_confirm_engineering()` when a LATER, independent
   `route_and_store()` call lands on the same ACTIVE engineering record
   (same `protocol` + `root_cause`, exact-string match) — i.e. a genuinely
   separate run re-deriving the same conclusion, not the same run reported
   twice.

Any gate miss returns `{"promoted": False, "reason": "..."}` — it never
raises for an ordinary miss, only for an unknown `memory_id`.

## Corner Case Library (`dv_harness.memory.CornerCaseLibrary`)

A separate class in the same file, at `.dv-harness/memory/corner_case_library/`.
Not one of the 5 tiers — routed via `kind == "corner_case"` +
`verified=True` → `CORNER_CASE_LIBRARY` destination, consolidated through
`CornerCaseLibraryConsolidator.from_resolved_corner_case()`
(`memory_router.py`'s `CORNER_CASE_LIBRARY` branch). Already wired into
`gates.py`'s `_ccl_reuse_verified()` for reuse revalidation
(`current_evidence_required`/`revalidate_by`/runtime-evidence checks) —
see MEMORY_SCHEMA.md for its field set.

## Confidence scoring (`dv_harness/inference.py`)

`score_confidence()` implements the real Hypothesis → Evidence →
Confidence → Gap → Next-Best-Action formula (see `debug-agent.md`'s
"v20 Autonomous Inference"):

```
base = min(independent_sources_count, 3) * 2
       + (2 if evidence_refs_verified else 0)
       - counter_evidence_count * 3
if multi_agent_consensus_count >= 2: base += 2
level = HIGH if base >= 6 else MEDIUM if base >= 3 else LOW
```

Safety floor: `counter_evidence_count > 0` can never coexist with a
reported `HIGH` — it is downgraded to `MEDIUM` with
`capped_by_counter_evidence: true`. `identify_gap()` and
`next_best_action()` (same module) round out the Gap/Next-Best-Action
half of the loop.

## The DV-Knowledge Vault (`dv_harness/memory_vault.py`)

See OBSIDIAN_INTEGRATION.md for the Vault's structure, the
`MemoryProvider` interface, and honest current Obsidian-availability
status. In one line: `HybridMemoryProvider` tries a real installed
Obsidian CLI per call when available (today, on every checked machine,
never), and always falls back to `FileSystemMarkdownAdapter` — the real,
fully-functional Markdown+YAML implementation — so the Vault is never
blocked by Obsidian's absence.

## The Memory Agent (`.claude/agents/memory-agent.md`)

See MEMORY_AGENT.md. The Memory Agent is the one designated caller for
search/retrieve/summarize/write/link/deduplicate/promote/demote/archive/
validate operations across all of the above — always through this real
API, never by hand-editing a memory file or vault note.

## Config (`dv_harness/config.py`)

```json
"memory": {
    "provider": "hybrid",
    "vault_path": "",
    "obsidian_cli": "auto",
    "git_enabled": false
}
```

`vault_path` empty resolves to a project-relative `.dv-harness/vault`
default (`memory_vault.resolve_vault_path()`) — never hardcoded to an
external path. `git_enabled` defaults `false` (opt-in): a real full-suite
regression run found that defaulting it `true` breaks Windows tmp-dir
cleanup in tests whose teardown never anticipated a `.git` tree appearing
inside them (git's read-only object files raise `PermissionError` on
`shutil.rmtree`) — a project that wants real git history for its vault
opts in explicitly.
