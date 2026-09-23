# CAP-M5-TOPTB-001 -- Capability Analysis

## Precise identification (Section 3) -- not inferred from the name

```
SOURCE_FILE     = dv_harness/reference_uvm_dut_top_integration_manifest.py
                  (442 lines, Parent-only, confirmed absent from canonical)
                  + dv_harness/uvm_generator/soc_environment_composer.py's
                  own wiring (a 104-line delta on top of the file already
                  merged under CAP-M5-ARCH-002)
SOURCE_SYMBOLS  = discover_existing_top_tb(), extract_existing_top_tb_facts(),
                  extract_top_tb_facts_from_text(), generated_top_tb_facts(),
                  compare_against_generated_top(), MATCH/DIVERGENT/
                  EXISTING_ONLY/GENERATED_ONLY/NOT_COMPARABLE vocabulary
INPUTS          = compose_soc_environment()'s existing (subsystem_registry_
                  entries, manifest, root) plus two NEW keyword-only params:
                  existing_top_tb_declared_path (str|None), force_fresh_top_tb
                  (bool, default False)
OUTPUTS         = files["soc_tb_top.sv"] (either the existing file's real
                  content, byte-for-byte, or _soc_tb_top()'s fresh output --
                  never a third, synthesized variant); soc_composition_
                  manifest.json gains a new "top_tb_composition" key naming
                  which path was taken and why
SIDE_EFFECTS    = a filesystem READ of the discovered candidate file (never
                  a write to it -- see Section 13 below); no other side effect
CALLERS         = the same 2 real production callers already identified under
                  CAP-M5-ARCH-002's caller sweep: dv_harness/uvm_generator/
                  create_environment.py (SYSTEM_LEVEL_MODE dispatch) and
                  dv_harness/engine.py (SYSTEM_LEVEL stage execution) -- both
                  already always pass a real `root`, confirmed by that
                  earlier sweep, re-confirmed unchanged this wave
CONSUMERS       = whatever reads soc_composition_manifest.json's new
                  "top_tb_composition" key downstream (none found this wave --
                  it is a new, additive audit-trail field, same shape as the
                  module's own "cross_subsystem_analysis" precedent)
TRIGGER         = every real SYSTEM_LEVEL_MODE composition where `root` is
                  supplied and `force_fresh_top_tb` is not True (i.e. the
                  DEFAULT path for both real production callers)
EXPECTED_BEHAVIOR = DISCOVER (name-convention or declared path) -> if FOUND,
                  extract real facts from both the existing file and a real
                  fresh _soc_tb_top() generation -> compare DUT instantiation
                  -> if not DIVERGENT, PRESERVE the existing file's real
                  content verbatim; if DIVERGENT, absent, or force_fresh_
                  top_tb_declared, fall back to fresh generation exactly as
                  before this capability existed
FAILURE_BEHAVIOR = no new exception type -- an unreadable/missing project
                  root degrades to the pre-existing NOT_FOUND/UNKNOWN
                  discovery states (never raises), and generation proceeds
                  via the fresh-generation fallback, same honest-degradation
                  discipline the rest of this module already uses
TEST_EVIDENCE   = 14 tests in Parent's dedicated dv_harness_tests/test_
                  reference_uvm_dut_top_integration_manifest.py (discovery,
                  fact-extraction, comparison, all 4 verdict states) + 6 new
                  tests in Parent's dv_harness_tests/test_soc_environment_
                  composer.py (end-to-end wiring: root=None unaffected,
                  force_fresh escape hatch, no-existing-file fallback,
                  preserved-verbatim positive case, EXISTING_ONLY-not-
                  DIVERGENT distinction, declared-path-beats-convention).
                  All 37 tests (both files combined) RUN THIS WAVE in
                  Parent's own frozen worktree (read-only) and PASSED.
```

## Chronology (resolves the apparent internal Parent inconsistency)

The discovery module's own docstring says top-TB preservation wiring is
"a deliberately DEFERRED follow-on task... not something this discovery
module may do" -- which reads, in isolation, as unimplemented. Checking
Parent's real git history resolves this:

- `705c469b` (2026-09-18): the discovery module itself is added, framed
  as deferred/future work at that time.
- `8d84394b` (2026-09-20), commit subject **"Wave 66 (HD-1): implement
  PRESERVE-qualified-DE-top-by-default"**: the project owner's explicit
  named human design decision (HD-1, V11 SS247) authorizing exactly the
  wiring the discovery module's own docstring said needed one. This
  commit wires `compose_soc_environment()` to the already-real, already-
  tested discovery module, adds 6 new composer tests, independently
  re-runs the 3 named caller-compatibility test files, and updates
  Parent's own `.dv-harness/l5dgva_audit_aggregate.py` audit tracking
  (closing a `C_ss247_top_tb_preservation_repaired` row, disclosed as
  WIRED_NOT_TRIGGERED-until-reachable, now reachable from both real
  production call sites).

**The discovery module's own docstring is simply stale** (written before
HD-1, never updated after) -- not evidence the feature is unapproved or
unimplemented. Per this task's own Section 3 instruction ("do not use the
capability name itself as proof of semantics"), the SAME discipline
applies in reverse here: do not use a stale docstring's OWN name/framing
as proof of non-implementation either -- verify against real git history
and real, run test evidence, which is what this analysis does.
