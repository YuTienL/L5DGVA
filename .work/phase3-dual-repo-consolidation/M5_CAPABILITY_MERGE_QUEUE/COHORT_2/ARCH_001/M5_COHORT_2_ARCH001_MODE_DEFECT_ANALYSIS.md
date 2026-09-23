# CAP-M5-ARCH-001 -- Known Mode-String Defect Analysis

## Re-investigation (not assumed from prior wave's characterization)

The "known hard-coded mode-string defect" is the SUBSYSTEM_MODE branch's
return statement:

```python
return {
    "environment_mode": "SUBSYSTEM_MODE",   # literal string, not decision["environment_mode"]
    ...
}
```

```
DEFECT_PRESENT_IN_CANONICAL = YES (literal string, confirmed by direct read)
DEFECT_PRESENT_IN_PARENT    = NO (Parent's diff fixes it: `decision["environment_mode"]`)
DEFECT_PRESENT_IN_V50       = YES (v50 is byte-identical to canonical for this file)
DEFECT_PRESENT_IN_B8        = YES (B8's diff does not touch this line at all)

AFFECTED_SYMBOL      = create_environment()'s SUBSYSTEM_MODE return dict
AFFECTED_CALLERS     = every real caller of create_environment() in SUBSYSTEM_MODE
                        (tools/generate_protocol_uvm_environment.py, all 11
                        PROTOCOL_BUILDERS skills via that CLI, and the 4 test
                        files that dispatch SUBSYSTEM_MODE)
EXPECTED_CONTRACT    = the returned `environment_mode` key reflects the REAL
                        resolved mode, not a value that happens to be correct
                        only because of a narrow dispatch condition
CURRENT_BEHAVIOR     = correct TODAY, for an incidental reason: the dispatch
                        condition (`decision["environment_mode"] ==
                        "SUBSYSTEM_MODE"`) already guarantees
                        decision["environment_mode"] is exactly
                        "SUBSYSTEM_MODE" whenever this return statement runs.
                        The hard-coded literal and the real value happen to
                        always agree today.
VERIFIED_SOURCE_BEHAVIOR = Parent's fix (`decision["environment_mode"]`)
                        removes the incidental-correctness dependency,
                        producing byte-identical output today (still always
                        "SUBSYSTEM_MODE" in that branch) while no longer being
                        fragile against a future widened dispatch condition.
FUTURE_M6_DEPENDENCY = the defect only becomes LIVE (produces a wrong
                        answer) once a future M6 wave widens the dispatch
                        condition to also match "IP_MODE" or any other mode
                        value -- which requires the M6-owned
                        verification_level.py/IP_MODE foundation
                        (CAP-M5M6-VLEVEL-001) to exist first. Today, in
                        canonical, that widening does not exist, so the
                        defect has zero observable effect.
```

## Classification

**IN_SCOPE_CAP_M5_ARCH_001.**

Rationale: fixing this now is a pure `M5_COMPATIBILITY_BEHAVIOR` change --
it does not implement any M6 VerificationLevel semantics (no `IP_MODE`
literal is added anywhere), it produces byte-identical output for every
real input canonical can construct today (verified by running the full
existing `create_environment()` regression suite unchanged after the
fix -- see `M5_COHORT_2_ARCH001_TEST_EVIDENCE.md`), and leaving it
unfixed would be "preserving a source implementation defect" rather than
"preserving verified capability semantics" (Section 9's own distinction).
Not fixing it would also leave a landmine for whichever future M6 wave
does widen the dispatch condition -- fixing it now, while it is free and
zero-risk, is squarely M5's job under "must not preserve or introduce
architecture that blocks IP/SUBSYSTEM/SYSTEM_LEVEL" (Section 7).

The OTHER three elements of Parent's same diff hunk cluster --
widening the dispatch condition itself to accept `"IP_MODE"`, the
`request["verification_level"]` evidence pass-through, and the
`if decision["requested_subsystems"]:` guard -- are **NOT** merged this
wave. All three are provably inert/dead code against canonical's real
`resolve_environment_mode()` (which never produces `"IP_MODE"` and can
never return an empty `requested_subsystems` in the SUBSYSTEM_MODE
branch, both verified by reading the router's full source, not assumed)
and all three presuppose Parent's own `verification_level.py` foundation,
which is `CAP-M5M6-VLEVEL-001`, still M6-owned and UNRESOLVED. Merging
them now would be exactly the "implement the full M6 model prematurely"
Section 7 forbids -- classified `M6_VERIFICATION_LEVEL_SEMANTICS`,
deferred.

```
MODE_STRING_DEFECT_DISPOSITION = RESOLVED
MODE_STRING_DEFECT_OWNER       = M5 (this capability)
```
