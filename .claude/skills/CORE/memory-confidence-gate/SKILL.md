---
name: memory-confidence-gate
description: 分離 historical memory confidence 與 current root-cause evidence confidence，避免自我確認。
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# memory-confidence-gate
分離 historical memory confidence 與 current root-cause evidence confidence，避免自我確認。

核心原則：Memory is prior knowledge, not current evidence.

## Mechanics (2026-09-03, real wiring)

**Purpose**: prevent a retrieved memory's OWN stored `confidence` field
from being reused, unchanged, as the current finding's confidence -- the
exact self-confirmation loop CLAUDE.md's Evidence Truth Rule forbids.

**Inputs**: a memory-retrieval result (each hit carries its own stored
`confidence`, e.g. from a prior `MemoryStore` record or vault note
frontmatter) AND separately, the current run's own evidence.

**Outputs**: two DISTINCT confidence values that must never be merged into
one number: (1) the retrieved memory's stored `confidence` (informational,
prior-knowledge only), and (2) `dv_harness.inference.score_confidence()`'s
result computed from THIS run's `independent_sources_count` /
`evidence_refs_verified` / `counter_evidence_count` /
`multi_agent_consensus_count`.

**Preconditions**: none to retrieve; but no memory-sourced confidence value
may be substituted for `score_confidence()`'s inputs.

**Execution Steps**:
1. Retrieve candidate memory (`memory-retrieval` skill / `MemoryRetriever.search()`
   / vault `search()`) -- note its `confidence` field for context only.
2. Independently gather THIS run's evidence: RTL/VIP/log/waveform per
   Evidence Truth Rule.
3. Compute `score_confidence()` using only current-run evidence counts.
4. Report both numbers separately when surfacing a finding -- never as one
   blended "confidence".

**Fallback**: if current-run evidence is not yet gathered, do not report a
confidence at all rather than substituting the memory's stored value.

**Evidence Requirements**: `score_confidence()`'s `evidence_refs_verified`
must correspond to evidence verified THIS run (a specific log
line/waveform/RTL citation), never "a similar memory said so".

**Failure Conditions**: `capped_by_counter_evidence` in `score_confidence()`'s
result (real counter-evidence forces HIGH down to MEDIUM, never silently
overridden) must be surfaced, not dropped, when reporting a finding.

**Example**: a retrieved Engineering Memory note says
`confidence: HIGH` for a similar-looking USB scoreboard mismatch from a
different port. That HIGH is a ranking signal only. This run's actual
`score_confidence(independent_sources_count=1, evidence_refs_verified=False,
counter_evidence_count=0, multi_agent_consensus_count=0)` -> `LOW` is the
number that must gate this run's own promotion decision.
