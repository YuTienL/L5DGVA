# USB Excel Gap-to-KC Extraction Contract

Status: registration only, reusing M8's existing real contract shape,
not inventing a new one.

## Experience Candidate (only for a real `KNOWLEDGE_GAP` root cause)

An Experience Candidate carries, at minimum:

```
identity              -- a stable ID for this candidate
project                -- which Canonical project
protocol               -- USB (this qualification's own scope) or the
                          generic protocol class, once known
level                  -- IP / SUBSYSTEM / SYSTEM_LEVEL
workbook               -- which Excel workbook/view surfaced the gap
field                  -- the specific Canonical field, if applicable
observed_gap           -- the gap taxonomy class (USB_EXCEL_GAP_TAXONOMY.md)
root_cause             -- the root-cause class (confirmed KNOWLEDGE_GAP)
evidence               -- the real evidence establishing the gap is genuine
applicability          -- USB_SPECIFIC / PROTOCOL_CLASS / GENERIC_DV / PROJECT_SPECIFIC (see below)
counterexamples         -- any known case where the proposed rule would NOT hold
confidence              -- using the existing Canonical Confidence vocabulary
proposed_knowledge      -- the actual candidate rule/lesson text
source_generation_id    -- which USB generation run produced this
qualification_id        -- which qualification run found this gap
```

## USB-specific vs. generic classification (never automatic)

```
USB_SPECIFIC   -- true only for this protocol; a USB-only observation
PROTOCOL_CLASS -- generalizes across a class of protocols sharing a real
                  structural property (e.g. all point-to-point serial
                  protocols with a similar handshake), evidenced, not assumed
GENERIC_DV     -- generalizes across DV methodology broadly, independent
                  of protocol
PROJECT_SPECIFIC -- true only for this specific project's own DUT/environment
```

A USB observation defaults to `USB_SPECIFIC`. Promotion to any broader
class (`PROTOCOL_CLASS`/`GENERIC_DV`) requires BOTH real applicability
evidence (a second, genuinely independent case where the same rule
correctly applies) AND a real counterexample search (a documented
attempt to find a case where it would NOT hold, with the result
recorded either way) — this is the same discipline
`memory_router.organizational_admission_gate()` already enforces via
`confirmation_count >= 2` from a genuinely different run, reused here
rather than reinvented.

## KC promotion flow (reuses M8's real gates, does not fork them)

```
Experience Candidate
  -> Evidence Sufficiency        (engineering_admission_gate()-shaped check:
                                   real evidence, HIGH/CONFIRMED confidence,
                                   a reusable root_cause/fix/lesson)
  -> Applicability                (which class: USB_SPECIFIC/PROTOCOL_CLASS/
                                   GENERIC_DV/PROJECT_SPECIFIC)
  -> Counterexample Search        (documented, both directions recorded)
  -> Generalization                (only if applicability + counterexample
                                    search both support it)
  -> Contradiction Check           (does this candidate conflict with any
                                    existing stored KC? if so, escalate,
                                    never silently overwrite)
  -> Promotion Gate                (organizational_admission_gate()-shaped:
                                    confirmation_count >= 2 from genuinely
                                    independent runs, for anything broader
                                    than PROJECT_SPECIFIC)
  -> KC (stored in the ONE Knowledge Brain, memory_router.py/memory_vault.py)
```

No USB-only Knowledge Brain, no second promotion gate, no second
storage mechanism. `ONE_KNOWLEDGE_BRAIN = YES` preserved.

## Provenance (required, not optional)

A promoted KC retains its full source chain: which qualification run,
which workbook/field, which gap, which RCA, which applicability
decision, and which promotion decision produced it. V2 (see
`USB_EXCEL_KC_REGENERATION_CONTRACT.md`) must be able to prove exactly
which KC influenced which generated item — a KC with no provenance
chain cannot satisfy the `KC_CONSUMPTION_REQUIRED_FOR_LEARNING_CLAIM`
gate.
