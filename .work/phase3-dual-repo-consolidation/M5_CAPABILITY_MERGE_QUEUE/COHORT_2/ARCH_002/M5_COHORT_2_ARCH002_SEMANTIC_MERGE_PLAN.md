# CAP-M5-ARCH-002 -- Semantic Merge Plan

## Verified behavior union (Section 16)

```
CANONICAL_CURRENT_BEHAVIOR = compose_soc_environment() always fresh-
  generates soc_tb_top.sv; _build_virtual_sequencer_fields() emits a
  plain evidence string per subsystem with no VIP-bind-chain awareness.

PARENT_VERIFIED_BEHAVIOR = a real, dated (2026-09-20) human design
  decision (V11 SS247): discover and preserve a qualified existing top
  TB instead of always regenerating, once root is supplied. Depends on
  dv_harness/reference_uvm_dut_top_integration_manifest.py -- CONFIRMED
  ABSENT from canonical (a third, previously-unregistered Parent-only
  module, distinct from the two already-registered M5 migration inputs
  task_boundary_conformance.py/intake_field_resolution.py).

B8_VERIFIED_BEHAVIOR = _subsystem_composition_mode() +
  _build_virtual_sequencer_fields() extension: an opt-in evidence
  annotation surfacing system_virtual_sequencer.py's DIRECT_HANDLE/
  ADAPTER_REQUIRED/COMPOSITION_UNDETERMINED verdict, when the caller
  supplies manifest["subsystem_vip_binds"]. system_virtual_sequencer.py
  itself already byte-identical between canonical and B8 (confirmed
  absent from Parent, per M0.5's own prior finding, independently
  re-confirmed this wave). B8 shipped and PASSED 3 real tests for this
  feature in its own worktree (verified this wave, not assumed).

VERIFIED_BEHAVIOR_UNION = B8's evidence-annotation wire, adopted verbatim
  (clean, tested, additive, no schema/contract change needed).

SEMANTIC_CONFLICTS = Parent's top-TB-preservation feature changes the
  DEFAULT output of both real production callers (create_environment.py
  AND engine.py both always pass a real root) the moment its dependency
  module exists -- but that dependency module does not exist in
  canonical. Not a code conflict to resolve; a missing-foundation
  situation, same shape as CAP-M5M6-VLEVEL-001's relationship to M6.

CANONICAL_TARGET_BEHAVIOR = B8's wire merged; Parent's top-TB feature
  deferred (registered as a new migration-input finding, not merged).

PRESERVED_BEHAVIOR = every existing compose_soc_environment()/
  _build_virtual_sequencer_fields() output for every input canonical can
  construct today without the new subsystem_vip_binds key (proven by the
  full existing regression suite passing unchanged).

SUPERSEDED_BEHAVIOR = none.

SOURCE_DEFECTS_NOT_PROPAGATED = none found in B8's soc_environment_
  composer.py delta this time (unlike ARCH-003/ARCH-001, this one had no
  signature mismatch or schema violation -- verified by running B8's own
  tests in B8's own worktree, all 20 passed).

DEFERRED_FUTURE_BEHAVIOR = Parent's top-TB preservation (V11 SS247) --
  requires its own dedicated migration-input analysis of
  reference_uvm_dut_top_integration_manifest.py (symbol inventory,
  caller sweep, test evidence) before it can be merged, since unlike
  every other capability closed so far, this one would change the
  DEFAULT output of the real production composition path the moment it
  lands, not merely add an opt-in.
```

## M9 genericity boundary (Section 7)

```
M5_VERIFIED_SOURCE_CAPABILITY = B8's evidence-annotation wire (a real,
  already-implemented, already-tested source behavior -- not invented
  for genericity's own sake)
M9_GENERICITY_SEMANTICS = none claimed. This wave does not assert
  GENERIC_SYSTEM_LEVEL = OPERATIONAL for anything beyond what B8's real,
  narrow evidence-annotation already proves. Cross-subsystem scenario/
  scoreboard/coverage content remains the deliberate NotImplementedError
  boundary in all 3 sources, unchanged.
```

## M6 Verification Level boundary (Section 8)

`soc_environment_composer.py` does not read or define any
IP/SUBSYSTEM/SYSTEM_LEVEL mode value itself -- SYSTEM_LEVEL_MODE is
selected upstream by `create_environment.py`'s dispatch (CAP-M5-ARCH-001,
already closed). This capability's own merge (B8's wire) is orthogonal
to mode/level entirely. No second VerificationLevel authority created.

## DE/DV generic-workflow compatibility (Section 9)

No DE/DV branching exists in this module in any source, before or after
this merge. `manifest["subsystem_vip_binds"]` is evidence about VIP bind
chains, not about who (human role) supplied it. `ONE_GENERIC_DE_DV_
WORKFLOW = YES`, preserved.

## Virtual sequencer dependency (Section 18)

`system_virtual_sequencer.py` confirmed absent from Parent (matches
M0.5's own finding), present and byte-identical between canonical and
B8, and DIFFERENT from v50's own copy (canonical's copy is already an
evolved/advanced version, not v50's original). This wave does not touch
`system_virtual_sequencer.py` at all -- only wires `soc_environment_
composer.py` to call its already-existing, already-canonical
`build_subsystem_composition()`. Zero regression risk to that module.

## Location independence (Section 22)

No new path/host/username dependency. `_subsystem_composition_mode()`
reads only from the caller-supplied `manifest` dict, exactly like every
other optional manifest key this module already supports.
`LOCATION_INDEPENDENT = YES`.
