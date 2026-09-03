---
name: project-memory
description: 保存已確認 DUT/SoC topology、VIP/UVM config、build/run flow、validated project conventions。
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# project-memory
保存已確認 DUT/SoC topology、VIP/UVM config、build/run flow、validated project conventions。

核心原則：Memory is prior knowledge, not current evidence.

## Mechanics (2026-09-03, real wiring)

**Purpose**: per-project, cross-session facts that stay true for the life of
a project's environment (topology, VIP/UVM config, build/run flow) --
distinct from Engineering Memory (a specific bug's root cause/fix).

**Inputs**: a record with `kind` in `project_fact` / `project_topology` /
`tool_flow` / `known_issue` AND `verified: true`. An unverified record with
one of these kinds falls through to WORKING_MEMORY instead (see
`route_memory()`) -- confirm the fact against current RTL/VIP/config
evidence before setting `verified`.

**Outputs**: `route_and_store()` returns
`{"destination": "PROJECT_MEMORY", "level": "project", "memory_id": ...}`
via `dv_harness.memory.ProjectMemoryStore`, under
`.dv-harness/memory/project/<memory_id>.json`.

**Preconditions**: `verified: true` is mandatory -- see Inputs above.

**Execution Steps**:
1. Confirm the topology/config/flow fact against current evidence
   (analysis-agent's SoC hierarchy/interface/topology discovery, or a
   completed environment-generation run).
2. `route_and_store(root, {"kind": "project_topology", "verified": True, ...}, cfg)`.
3. Retrieve later with `python -m dv_harness.memory_cli search --scope <scope> --text <query>`
   or the `memory-retrieval` skill before re-deriving topology from scratch.

**Fallback**: if the fact cannot yet be independently verified, write it to
Working Memory (`verified` omitted/false) instead of forcing a Project
Memory write.

**Evidence Requirements**: current RTL/SoC hierarchy discovery, or a
completed, evidenced build/run -- never carried over unverified from a
different project (Evidence Truth Rule).

**Failure Conditions**: a stale topology fact that no longer matches current
RTL must be corrected via `memory-gc` (`flag_stale`/`retract`), never left
silently wrong.

**Example**:
```python
route_and_store(root, {
    "kind": "project_topology", "verified": True, "protocol": "USB",
    "scope": "branch_a0", "title": "USB DUT has 2 ports, 0-indexed per RTL top",
}, cfg=cfg)
```
