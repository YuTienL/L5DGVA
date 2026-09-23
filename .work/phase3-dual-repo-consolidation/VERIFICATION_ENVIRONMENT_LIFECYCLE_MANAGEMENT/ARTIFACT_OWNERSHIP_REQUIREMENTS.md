# Artifact Ownership Requirements

ROADMAP requirements only. No production code implements this document.

## The five ownership classes

```
L5_MANAGED       -- fully harness-generated
USER_MANAGED     -- human/DE-authored
SHARED_MANAGED   -- co-owned, requires controlled semantic merge
GENERATED_REGION -- a regenerable marker-delimited region inside a
                     larger file of any other ownership class
PROTECTED        -- requires explicit authority before any modification
```

These are not a competing schema -- see
`VERIFICATION_ENVIRONMENT_LIFECYCLE_ARCHITECTURE.md`'s ownership-model
table for the real Canonical precedent each class is grounded in.
`L5_MANAGED` and `USER_MANAGED` already have real, working mechanisms
(`ProtocolEnvGenerator`'s fresh-generation path; `CAP-M5-TOPTB-001`'s
preservation path, respectively). `SHARED_MANAGED`, `GENERATED_REGION`,
and `PROTECTED` are named and required here but have no callable
mechanism yet -- roadmap requirements for M10.5, not claims of existing
capability.

## Frozen safety principles (non-negotiable requirements, not suggestions)

1. **`USER_MANAGED` artifacts must not be automatically overwritten.**
   Already enforced in the one real instance that exists:
   `compose_soc_environment()` never writes to a discovered existing top
   TB's own on-disk path -- it only reads it and returns its content for
   the CALLER to write to a separate composition output directory. Any
   future `USER_MANAGED` mechanism must preserve this "read the original,
   never mutate it in place" discipline.
2. **`PROTECTED` artifacts require explicit authority before
   modification.** The authority model is the existing `question_queue.py`
   `HUMAN_DECISION_SOURCE` mechanism, already proven (this session's own
   M5-0 checkpoint required explicit human approval before every wave) --
   not a new approval mechanism.
3. **`L5_MANAGED` artifacts may be regenerated only under provenance and
   lifecycle contracts.** "Provenance" here means the real, already-
   demonstrated discipline: every fact this session's own new capabilities
   cite carries a real evidence trail (sha256 content hashes, line-number
   citations, real test evidence) -- never a bare "regenerated" claim with
   nothing behind it.
4. **`SHARED_MANAGED` artifacts require controlled semantic merge.**
   "Controlled" means the SAME discipline this session's own M5 Cohort 1/2
   work already demonstrated by hand (symbol-level comparison, real
   defect detection before merging, never a textual 3-way merge treated as
   authority) -- `UVM_SEMANTIC_MERGE` (`CAP-VELM-010`)'s job is to make
   that discipline a callable capability, not to invent a new, lower-rigor
   shortcut.
5. **Regeneration must not mean whole-environment overwrite.**
   `CAP-M5-TOPTB-001` already demonstrates file-by-file granularity is
   achievable in this codebase (three files independently decided within
   one `compose_soc_environment()` call); `SAFE_INCREMENTAL_REGENERATION`
   (`CAP-VELM-009`) generalizes this, it does not invent the concept from
   nothing.

## Validation

```
ARTIFACT_OWNERSHIP_MODEL = ROADMAP_DEFINED
USER_MANAGED_OVERWRITE_ALLOWED = NO
```

No new competing schema created; no duplicate of `question_queue.py`'s
authority model created; no second provenance mechanism created.
