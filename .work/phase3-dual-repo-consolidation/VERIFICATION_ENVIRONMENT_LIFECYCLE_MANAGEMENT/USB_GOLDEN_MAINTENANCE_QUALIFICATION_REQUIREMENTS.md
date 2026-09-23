# USB Golden -- Quad Qualification Requirements (M11)

ROADMAP requirement registration only. Does not start M11 or M10.5.

**Extended this wave** (DV Verification Environment Lifecycle
Integration reconciliation, Section 32): the original A/B dual
qualification is now a quad (A/B/C/D) qualification, adding the Native
Claude Fast Maintenance dimension. Title updated to "Quad" to reflect
this; nothing in A/B below is weakened.

## Frozen requirement

M11 (USB Golden Qualification) must qualify **all four**:

```
A. FROM-SCRATCH generation -- the existing CREATE_LIFECYCLE qualification
   this wave (USB_UVM_Handoff as the canonical structural template,
   No-Golden-Reference-Content-Mining-compliant generation) already
   targets. Unchanged by this reconciliation.

B. MAINTENANCE of an existing qualified USB environment after a real
   RTL/spec change, while preserving user customization -- exercising
   the MAINTAIN_LIFECYCLE this document's sibling artifacts define.

C. A bounded maintenance defect solved through Native Claude Fast Path
   -- new this wave. A real, disclosed, small-scope defect (bounded per
   FAST_PATH_ELIGIBILITY's own 10 conditions) resolved entirely inside a
   Fast Path session, never invoking Full L5DGVA orchestration.

D. A Fast Path task correctly escalating to Full L5DGVA with context/
   evidence preserved -- new this wave. A real, disclosed scenario where
   a Fast Path session begins bounded and then genuinely expands (one of
   the 15 real escalation triggers in FAST_PATH_ELIGIBILITY_AND_
   ESCALATION.md fires), and the resulting Full L5DGVA session
   demonstrably does NOT restart from zero -- the FAST_TO_FULL_CONTEXT_
   HANDOFF_CONTRACT.md record is real evidence of this, not merely
   claimed.
```

Neither qualification substitutes for another. A. proves the generator
produces a correct environment from nothing; B. proves the SAME generator
family can correctly evolve an already-qualified environment without
destroying what a DE/DV team already built on top of it; C. proves the
lightweight execution mode is real and sufficient for genuinely bounded
work; D. proves the lightweight mode's own honesty about its limits --
that it correctly recognizes when it is no longer the right tool and
hands off cleanly rather than either refusing everything or silently
overreaching.

## What (B) concretely requires, mapped to real `CAP-VELM-*` capabilities

```
A real, qualified USB environment must already exist            (M11
  prerequisite -- (A) must close first, or an equivalent qualified
  fixture must exist)
A real RTL/spec change must be applied to the USB DUT             (test
  input -- not fabricated; a real, disclosed delta)
CAP-VELM-006 (Semantic Change Detection) must correctly identify what
  changed
CAP-VELM-007 (Verification Change Impact Analysis) must correctly scope
  what verification content is affected
CAP-VELM-004 (Artifact Ownership Model) must correctly distinguish
  L5_MANAGED regenerable content from USER_MANAGED content the DE/DV
  team customized on top of the original generation
CAP-VELM-009 (Safe Incremental Regeneration) must regenerate only the
  affected L5_MANAGED artifacts, never the whole environment
CAP-VELM-010 (UVM Semantic Merge) must correctly reconcile any
  SHARED_MANAGED content
CAP-VELM-011 (Selective Regression) must run only the regression subset
  the real change impact actually touches
CAP-VELM-012 (Coverage Delta) must show the real coverage delta the
  change produced
CAP-VELM-013/014 (Evidence Invalidation / Incremental Re-Signoff) must
  correctly invalidate only the evidence the change actually affects and
  re-signoff only that scope
```

Every one of these is `ROADMAP_DEFINED`, not implemented -- this
document registers the requirement chain, it does not close any link in
it.

## Explicit customization-preservation requirement

The maintenance qualification is not satisfied by merely "regeneration
still runs." It requires a real, disclosed test fixture where a DE/DV
team's own real customization (analogous to `CAP-M5-TOPTB-001`'s own
`USER_MANAGED` top-TB precedent, generalized to USB-specific content --
e.g. a hand-added checker, a hand-tuned constraint, a hand-authored
sequence layered on top of the generated skeleton) survives the RTL/spec-
change-driven regeneration byte-for-byte where the change did not
actually touch it, and is correctly flagged (never silently discarded)
where the change did.

## What (C) and (D) concretely require, mapped to real `CAP-VELM-*` capabilities

```
CAP-VELM-019 (Native Claude Fast Maintenance) must be operational enough
  to run a real, bounded USB maintenance session end-to-end
CAP-VELM-021 (Fast Path Eligibility) must correctly classify the (C)
  scenario as eligible and the (D) scenario as initially-eligible-then-
  triggered
CAP-VELM-022 (Fast Path Escalation to L5DGVA) must correctly fire on the
  real trigger the (D) scenario exercises
CAP-VELM-023 (Fast-to-Full Context Handoff) must produce a real handoff
  record for (D) that a Full L5DGVA session can genuinely resume from
  without re-deriving what Fast Path already established
```

Every one of these is `ROADMAP_DEFINED`, not implemented -- same
disclosure as (A)/(B) above.

## Validation

```
USB_GOLDEN_FROM_SCRATCH_QUALIFICATION = unchanged, existing M11 target
USB_GOLDEN_MAINTENANCE_QUALIFICATION  = ROADMAP_DEFINED
USB_GOLDEN_FAST_PATH_QUALIFICATION    = ROADMAP_DEFINED (new this wave,
                                          ZERO implementation)
USB_GOLDEN_FAST_TO_FULL_ESCALATION_QUALIFICATION = ROADMAP_DEFINED (new
                                          this wave, ZERO implementation)
M11_STARTED = NO
M10_5_STARTED = NO
```
