# M7 Preflight -- Output Consumption Architecture

Per this task's own explicit instruction: "M7 cannot claim integration
merely because Claude produced a file / Codex produced a review / ChatGPT
produced advice." For every model path, the real
OUTPUT -> Parser/Adapter -> Validation -> EvidenceRefs -> Canonical
Consumer -> Next Workflow Stage chain, tracked honestly against CURRENT
canonical state.

## Claude CLI (the ONE model path with a complete chain today)

```
MODEL_OUTPUT_PRODUCED  = YES (a real file edit / AgentResult)
MODEL_OUTPUT_PARSED    = YES (the caller reads AgentResult.ok/raw/text directly)
MODEL_OUTPUT_VALIDATED = YES (real validators: ValidationState, _verification_
                          level_validator, task_boundary_conformance's own
                          classification, structural lint, VIP API validation)
MODEL_OUTPUT_CONSUMED  = YES (create_environment()'s own output feeds the
                          NEXT stage -- e.g. a generated environment_
                          manifest.json is real, real generation evidence,
                          real downstream file)
```

This is the ONLY model path in this project where the full chain is
proven, production-connected, and qualified (M6's own 10-stage slice).

## Codex

```
MODEL_OUTPUT_PRODUCED  = NO (canonical: zero Codex invocation exists at
                          all, confirmed fresh this pass -- see
                          M7_EXISTING_CAPABILITY_AUDIT.md)
MODEL_OUTPUT_PARSED    = N/A (nothing produced to parse)
MODEL_OUTPUT_VALIDATED = N/A
MODEL_OUTPUT_CONSUMED  = NO
```

Even in Parent (never migrated to canonical), the 3 real package-
assembly modules explicitly, repeatedly self-block
(`BLOCKED_NO_EXTERNAL_REVIEWER`, `codex_review_has_occurred=False`
hard-coded, `NOT_PROVEN_REQUIRES_CODEX_TOOL` hard-coded) -- meaning even
THERE, `MODEL_OUTPUT_PRODUCED` was never true for a real review; the
modules produce a real, well-formed REVIEW REQUEST PACKAGE, not a
review result. Nothing in either tree parses/validates/consumes an
actual Codex verdict.

## ChatGPT

```
MODEL_OUTPUT_PRODUCED  = OBSERVED_ONCE, OUTSIDE_TOOLING (Parent's own
                          .chatgpt-handoff/round2c/ artifacts, dated
                          2026-09-09, are the STAGED INPUT to ChatGPT, not
                          its output -- ChatGPT's own reply was pasted
                          back by a human into some OTHER, untracked
                          location; no NEXT_CODEX_PROMPT.md or equivalent
                          return artifact was ever observed, in either
                          tree)
MODEL_OUTPUT_PARSED    = NO
MODEL_OUTPUT_VALIDATED = NO
MODEL_OUTPUT_CONSUMED  = NO
```

The pipeline's own return leg was never observed to complete even once.

## Reading this honestly

Of the 4 tracked stages (`PRODUCED`/`PARSED`/`VALIDATED`/`CONSUMED`),
Claude CLI is the only path with all 4 real. Codex has 0/4 in canonical
(0/4 effectively in Parent too, since "producing a review REQUEST" is
not "producing a review"). ChatGPT has, generously, a partial/unproven
0.5/4 (an OUTBOUND artifact was staged and evidently used by a human at
least once, but nothing INBOUND was ever captured, parsed, validated, or
consumed by any Canonical mechanism).

## What M7's own first implementation cohort must build to close this
(scoped here, not built here -- this is PREFLIGHT, not implementation)

For EITHER Codex or ChatGPT to graduate past `HUMAN_MEDIATED_ONLY`
(`M7_MODEL_ROLE_MATRIX.csv`) into `AUTOMATABLE_NOW`, all 4 stages need a
real, evidenced producer:

1. `MODEL_OUTPUT_PRODUCED`: a real, tracked artifact path (not "a human
   pasted something somewhere untracked").
2. `MODEL_OUTPUT_PARSED`: a real parser turning that artifact into a
   structured record -- reusing the `EXPECTED_OUTPUT_SCHEMA` shape from
   `M7_STRUCTURED_HANDOFF_CONTRACT.md`.
3. `MODEL_OUTPUT_VALIDATED`: reusing the real `ValidationState`/
   `validator=` pattern already proven in `intake_field_resolution.py`/
   `clarification_service.py`.
4. `MODEL_OUTPUT_CONSUMED`: a real Canonical consumer that changes
   behavior/state because of the validated output (e.g. a real question
   filed, a real gate blocked, a real fact persisted) -- not merely
   printed or logged.

See `M7_IMPLEMENTATION_COHORT_PLAN.md` for where this lands in the
dependency-ordered cohort sequence.
