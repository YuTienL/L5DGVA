# CAP-M5-TOPTB-001 -- Disposition

## Canonical equivalence (Section 6)

`CANONICAL_EQUIVALENT = NO`. Grep for `discover_existing_top_tb`/
`top_tb_composition`/preservation-shaped logic anywhere in canonical's
`dv_harness/` -- zero matches, confirmed fresh this wave. No partial or
disguised equivalent found either (not just a filename comparison --
`soc_environment_composer.py`'s own `_soc_tb_top()` was read in full
during CAP-M5-ARCH-002 and contains no discovery/preservation logic of
any kind).

## v50/worktree equivalence (Section 7)

`v50`: file absent, no equivalent behavior. `B7A`/`B7B`: no prior finding
in this session (including CAP-M5-ARCH-002's own full analysis of this
exact file) identifies either as a contributor to this capability. `B8`:
contributes only the already-merged ARCH-03 evidence-annotation wire,
confirmed to not touch top-TB preservation at all. **Parent remains the
sole and strongest verified source.**

## M9/M5 ownership boundary (Section 10)

This capability preserves an **already-verified source generation
behavior** (Parent's own, human-decision-gated, fully tested) -- per
Section 10's own rule, "if capability is required to preserve an already
verified source generation behavior, that favors M5 migration." It does
not depend on any not-yet-built M9 generic IP/Subsystem/System-Level
architecture; SYSTEM_LEVEL_MODE composition already exists and is
already real (CAP-M5-ARCH-002 territory). The explicitly-deferred EXTEND
follow-on (splicing new VIP/UVM hooks into a preserved top TB) is the one
piece that genuinely depends on future generic architecture -- correctly
left deferred, un-implemented, in Parent itself.

```
M5_CORE_PRESERVATION  = the DISCOVER->QUALIFY->PRESERVE mechanism itself
                         (this wave's migration scope)
M9_FUTURE_EXTENSION   = EXTEND (VIP/UVM hook splicing into a preserved
                         top) -- not implemented in Parent, not migrated
                         here, correctly left for a future M9-adjacent
                         wave if/when Parent (or another source) actually
                         builds it
```

## Article 0 (Section 14)

```
LOCATION_INDEPENDENT    = YES (all paths repository/project-root-relative;
                           see Section 12 verification below)
EVIDENCE_GROUNDED       = YES -- every comparison verdict cites both
                           sides' real extracted text/line evidence, never
                           a bare boolean
KNOWLEDGE_DRIVEN        = N/A directly (this is generation-path evidence
                           discovery, not knowledge-brain retrieval)
CONTINUOUS_EVOLUTION    = N/A this wave
END_TO_END_DV_ALIGNMENT = PARTIAL -- closes one real gap in the SYSTEM_
                           LEVEL_MODE generation path (previously: always
                           silently discarded a real existing top TB);
                           does not complete end-to-end DV alignment on
                           its own
```
No final Constitutional Compliance claimed.

## File safety (Section 13) -- reviewed, not redesigned

- **Atomicity**: N/A for reads. The one write this capability's OWN code
  performs is none -- `_run_verification_architecture`-style writes don't
  apply here; the actual disk write of `soc_tb_top.sv` happens in the
  CALLER (`create_environment.py`/`engine.py`), unchanged by this
  capability, using whatever write mechanism those callers already use.
- **Overwrite protection**: this capability never writes to the
  DISCOVERED file's own original path -- it only READS it and returns
  its content for the caller to write to the SEPARATE composition output
  directory (`generated/soc_composition/<soc_name>/`). The original
  hand-authored file, wherever discovered, is never modified or deleted.
- **Path validation / repository boundary**: `discover_existing_top_tb()`'s
  `declared_path` parameter resolves via plain `Path` join
  (`root / declared_path`), which does not itself sanitize `..`
  traversal -- but this exactly mirrors `subsystem_discovery.py`'s own
  pre-existing `declared` parameter precedent (the module's own docstring
  names this explicitly), is driven only by the SAME trusted local
  caller that already has full filesystem access to the project (not an
  external/untrusted input), and introduces no NEW privilege boundary
  beyond what the rest of this codebase's discovery mechanisms already
  accept. Not expanded into a full security redesign, per this section's
  own instruction; flagged here as reviewed and accepted, consistent with
  existing precedent, not a new risk this migration introduces.
- **Symlink handling**: not specially handled (neither by this module nor
  by `subsystem_discovery.py`'s own walk, which this module reuses
  verbatim) -- same existing, accepted behavior, not a new gap.

## Primary disposition (Section 15)

```
PRIMARY_DISPOSITION = MIGRATE_WITH_ADAPTATION
```

Not `MIGRATE_AS_IS`: the migration includes registering the real
idempotency nuance this wave found (Section 9) as disclosed, tested-gap
documentation -- a real adaptation of understanding, even though zero
lines of Parent's actual code need to change (both the production module
and its 20 combined tests are migrated verbatim, byte-for-byte, since no
defect was found). "Adaptation" here means integrating it correctly into
canonical's own file layout/import paths and porting its test coverage
completely -- not code alteration.

Not `DEFER`: every exit-criteria question this task poses (operationality,
canonical equivalence, ownership, preservation semantics, security) has a
real, evidence-backed answer, and no missing foundation remains (unlike
the original ARCH-002-wave concern, which is now resolved: the "missing
dependency" WAS this exact module, now being migrated in full).

Not `HUMAN_DECISION_REQUIRED`: the human decision was already made, by
the project owner, in Parent's own history (HD-1, V11 SS247,
2026-09-20) -- re-litigating it here would be redundant, not additional
rigor.
