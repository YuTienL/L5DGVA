# M1 — KNOWN_SOURCE_B_DEFECT Disposition (`create_environment.py` hardcoded mode string)

Per instruction #7. Investigated read-only during M1 (no file modified) to confirm
the defect still exists exactly as previously recorded and to check for an
existing fix-wave assignment before deciding M1's disposition.

## Confirmed defect (re-verified against current v50 HEAD, not assumed from prior docs)

`D:\DV\Task\DV_Agent_Harness_L5\v50\dv_harness\uvm_generator\create_environment.py`:
- Line 346: `if decision["environment_mode"] == "SUBSYSTEM_MODE":` (only checks one mode)
- Line 380: `"environment_mode": "SUBSYSTEM_MODE",` (hardcoded literal in the result, regardless of what was actually resolved)

Parent's equivalent (`D:\DV\Task\DV_Agent_Harness_L5\dv_harness\uvm_generator\create_environment.py`) is correct:
- Line 349: `if decision["environment_mode"] in ("SUBSYSTEM_MODE", "IP_MODE"):`
- Line 384: `"environment_mode": decision["environment_mode"],` (echoes the real resolved value)

**New confirming fact, verified fresh**: v50's own `environment_mode_router.py` has
no `IP_MODE` concept at all today (zero hits) — it only ever resolves
`SUBSYSTEM_MODE`/`SYSTEM_LEVEL_MODE`. So in v50 as it stands, this defect is
currently **latent** (the hardcoded branch can never actually diverge from
reality yet) — it becomes a live functional bug only once IP_MODE support is
merged in from Parent's router logic, which is exactly what Wave M5 already
plans to do to this same file.

## Existing fix-wave assignment: YES, explicit (found, not newly assigned here)

- `M_MINUS_1_ARCHITECTURE_DECISIONS.md` D6: recorded as `KNOWN_SOURCE_B_DEFECT`; "v50 itself is not modified ... The canonical implementation, when Wave M5 ... reaches uvm_generator/create_environment.py, must fix this defect using parent's correct logic and add a regression test."
- `17_CANONICAL_MIGRATION_WAVES.md`: Wave M5, priority #2 of 8 `SEMANTIC_CONFLICT` files; explicitly coupled ("amended") into a 3-way reconciliation together with `b8`'s `ARCH-01` capability port, "applied together with the existing KNOWN_SOURCE_B_DEFECT fix in the same pass."
- `M0_5_B8_CAPABILITY_AUDIT.md`: flags the coupling explicitly — both the defect fix and ARCH-01 touch the same function's generation-request-handling logic, so they must land in one pass, not sequentially.

## M1 disposition

**Deferred to Wave M5** (`ENTANGLED_DEFER_TO_LATER_WAVE`), not fixed now, for four
concrete reasons: (1) v50 is explicitly frozen — D6 forbids modifying it directly;
(2) there is no canonical merged `create_environment.py` yet to apply the "real"
fix to — that file is a planned Wave-M5 artifact, not something this standalone
patch could land into; (3) the fix is explicitly coupled to the `b8`/`ARCH-01`
capability port in the same reconciliation pass, per governance already on
record; (4) the "correct" behavior depends on `IP_MODE` existing in whichever
`environment_mode_router.py` ends up canonical — a cross-file dependency, not
contained to this one file.

```
KNOWN_SOURCE_B_DEFECT_STATUS = KNOWN_SOURCE_B_DEFECT_PRESERVED_FOR_LATER_FIX
KNOWN_SOURCE_B_DEFECT_ASSIGNED_WAVE = M5 (coupled with b8/ARCH-01 in the same pass)
KNOWN_SOURCE_B_DEFECT_QUALIFICATION_OBLIGATION:
  Wave M5 must add a regression test that (a) fails against v50's current
  hardcoded "SUBSYSTEM_MODE" behavior and (b) passes against the corrected
  canonical behavior (parent's `in ("SUBSYSTEM_MODE", "IP_MODE")` grouping,
  echoing the real resolved environment_mode) -- and must land in the same
  commit/pass as the b8/ARCH-01 port, per the coupling above, not sequentially.
```

Not mixed with this session's unrelated M1 bootstrap work, per instruction #7.
