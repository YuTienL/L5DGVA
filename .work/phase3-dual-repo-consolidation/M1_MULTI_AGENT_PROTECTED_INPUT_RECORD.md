# M1 — multi_agent.py Protected Migration Input Record

Per instruction #6: do NOT copy or apply the dirty source `multi_agent.py`
diff during M1. This file records the protected status only.

```
PROTECTED_MIGRATION_INPUT = TRUE
CAPABILITY_ID = PH0-PREDISPATCH-FRESHNESS-INTEGRATION-001 (Track A)
SOURCE = D:\DV\Task\DV_Agent_Harness_L5\dv_harness\multi_agent.py
         (PARENT repo's own dirty working tree, uncommitted -- 101
         insertions / 5 deletions per `git diff --stat`)
MULTI_AGENT_PROTECTED_CAPABILITY_RECORDED = YES
MULTI_AGENT_DIRTY_DIFF_APPLIED = NO
```

**Correction, disclosed**: an earlier draft of this record (and this session's own
pre-compaction summary) misstated the source as `v50/dv_harness/multi_agent.py`.
Re-verified directly just now: v50's own `dv_harness/multi_agent.py` (`git status`,
`git diff --stat`) is currently **clean** and does **not** contain this
capability at all (confirmed by grep: zero hits for
`find_completed_task_by_identity`/`find_active_task_by_identity` in v50's
copy). The real dirty delta lives only in the **Parent** repository's own
`dv_harness/multi_agent.py` at the parent root -- exactly the file the
session's standing rule already protects ("Never modify/stage/commit
dv_harness/multi_agent.py in that [Parent] repo"). This correction does not
change the disposition below (still `PROTECTED_MIGRATION_INPUT`, still not
applied), only the recorded source path.

Full symbol/behavioral-contract capture already exists (not recomputed, per
the M0.5/M0.6 "do not recompute" rule) at
`M0_6_PROTECTED_MIGRATION_INPUTS.md`, which specifies the exact capability
reserved for a future semantic-reimplementation wave:

- `AgentTaskStore.create_task(self, agent, route, skills, parent_plan, parallel_group=None, depends_on=None, work_identity=None)` — extended signature, backward-compatible
- `find_completed_task_by_identity(self, work_identity)` and `find_active_task_by_identity(self, work_identity)` — both: `work_identity=None` never matches anything
- `MultiAgentOrchestrator`'s dispatch method's suppression logic: `predispatch_freshness.classify_work_item_freshness()` → `COMPLETED`/`COMPLETED_BUT_STATE_STALE` suppresses with `freshness_verdict=<verdict>, dispatch_suppressed=True`; else `find_active_task_by_identity()` → suppress as `DUPLICATE_ACTIVE_LEASE`; else create new task, `freshness_verdict='DISPATCHED_FRESH', dispatch_suppressed=False`

**Verified unchanged in this canonical repository**: `dv_harness/multi_agent.py`
in `D:\DV\Task\L5_DGVA` was cloned from v50's committed HEAD only, confirmed
identical to v50's own current working-tree copy of the same file (`diff`,
zero output) — and, per the correction above, the dirty delta lives only in
the *Parent* repository's own working tree, which was never read into, copied
into, or merged into the canonical repository during M1. This capability
therefore correctly remains absent from L5_DGVA, exactly as required for a
`PROTECTED_MIGRATION_INPUT` still awaiting semantic reimplementation.

Disposition: reserved for semantic reimplementation in the assigned later
migration wave (M6, per the M0.6 disposition), never a mechanical patch-apply.
