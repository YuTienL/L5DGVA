# M7 R005-2 Final Truthful Disposition

Per the M7 Convergence prompt, section 5: this is NOT a force-closure.
R005-2 is re-verified against the REAL, currently-exercised publication/
transport contract, not against what the code is theoretically CAPABLE of
if a producer adopted every available mechanism.

## The real, current transport contract

Every Codex round trip this M7 program has actually run
(REVIEW-003→004, 004→005, 005→006) used the SAME real mechanism:

1. `dv_harness/model_handoff_workflow.export_handoff()` writes
   `HANDOFF_V1.md` and registers `expected_result.json`.
2. A HUMAN copies/relays the handoff content to Codex outside this
   repository (an external tool, not something L5DGVA code invokes).
3. Codex produces `RESULT_V1.md` text; a HUMAN places it at the exact
   registered expected path.
4. The already-running detached watcher (`result_ingestion.watch()`)
   detects it via its own multi-observation `_observe()` stability
   check (`quiet_seconds`/`min_observations`, no manifest, no seal) and
   calls the Canonical `ingest_result_file()` -> `import_result()` chain
   with ZERO further human action.

At NO point in any of the three real round trips so far did a manifest
sidecar (`<result>.manifest.json`) exist. Verified directly: none of
`M7-V1-CODEX-REVIEW-004`, `-005`, `-006`'s result directories contain one.

## Classification

``` text
SEALED_PUBLICATION = NO
LEGACY_UNSEALED_PUBLICATION = COMPATIBILITY_MODE
QUALIFIED_ATOMIC_PUBLICATION = NO
```

The real transport contract in actual current use is `partial/temp result
-> complete write/close -> [NO digest/seal step] -> atomic-enough-for-a-
human-editor publication -> watcher ingestion`. It skips the
digest/seal/manifest step Codex's own recommended fix names. This is
LEGACY_UNSEALED_PUBLICATION, in COMPATIBILITY_MODE (the pre-existing,
still-default behavior every prior review round also ran under, R005-1/2/3
and R006-1/2/3 remediation included).

## Why this is not force-closed, and not silently expanded either

REVIEW-006's own R006-4 finding independently re-confirmed R005-2's
characterization is accurate and NOT a newly introduced regression: "This
is accurately disclosed by the remediation report and is not a newly
introduced regression, but it remains an unresolved qualification failure
for the current human-transport path." This is now the SECOND independent
Codex re-review to reach the same conclusion (REVIEW-006 re-verifying
REVIEW-005's own honest disclosure), which is itself real, if narrow,
evidence that the disclosure is accurate rather than a convenient
downgrade.

A real, tested, opt-in mitigation exists (`_sealed_manifest_confirms_
completion()`, closed for its own TOCTOU race in REVIEW-006 R006-2) but is
not exercised by the actual current transport, because closing R005-2 by
DEFAULT requires a transport-CONTRACT change: either the human/Codex-side
process starts writing a `.manifest.json` sidecar, or the watcher's own
`_observe()` state machine is redesigned to require positive completion
proof instead of quiet-interval inference for every producer. Both are
changes to how content ARRIVES at this repository from OUTSIDE it -- this
session has no unilateral control over the first (a human/Codex behavior
change) and the second would be a materially larger redesign of the
watcher's own persisted state machine (see "Considered and deferred"
below), disproportionate to fold into this convergence pass without a
separate, dedicated wave.

## Disposition

``` text
PRIMARY_CLASS = CURRENT_SCOPE_CORRECTNESS_BLOCKER (by strict definition:
  a real, reproduced, currently-shipped narrower-than-stated guarantee)
DISPOSITION = HUMAN_DECISION_REQUIRED (risk-acceptance, not a code defect
  this session can unilaterally resolve or silently downgrade)
BLOCKS_M7 = PENDING HUMAN DECISION (see HumanGate below) -- NOT
  auto-resolved to either YES or NO by this report
OWNER = project owner (human)
WAVE = a dedicated "Sealed Transport Contract" wave, not folded into M7
  convergence
```

This session declines to unilaterally decide "acceptable" or
"unacceptable" on the project owner's behalf -- that is a real
risk-acceptance judgment, not a fact this session can derive from
evidence alone, and self-approving it would repeat exactly the
"DO NOT SELF-APPROVE HUMAN AUTHORITY" mistake this program has
consistently avoided for the Claude-worker permission question.

### HumanGate

```
AUTHORITY_TYPE = RISK_ACCEPTANCE
QUESTION = Accept LEGACY_UNSEALED_PUBLICATION / COMPATIBILITY_MODE as
  sufficient for M7 sign-off (given: two independent Codex reviews found
  no NEW defect from it, and the realistic human-copy-paste transport
  pattern has not, in three real round trips, actually exhibited the
  demonstrated pathological-timing failure mode) -- OR block M7 pending a
  sealed-transport-contract wave that requires either the human/Codex
  transport step to write a completion manifest, or a redesign of the
  watcher's own stability state machine?
OPTION_A = ACCEPT_AS_NON_BLOCKING (record R005-2/R006-4 as
  PRE_EXISTING_OWNED_GAP with this exact disclosure, proceed to M7 closure
  once other criteria are met)
OPTION_B = BLOCK_M7_PENDING_SEALED_TRANSPORT_WAVE (open a new, dedicated
  wave; M7 cannot reach READY_FOR_APPROVAL until it lands)
EVIDENCE = M7_CODEX_REVIEW_005_FINDINGS_REMEDIATION_REPORT.md,
  M7_CODEX_REVIEW_006_FINDINGS_REMEDIATION_REPORT.md,
  dv_harness_tests/test_model_handoff_review005_remediation.py::
  test_slow_writer_pausing_longer_than_quiet_interval_can_still_be_
  consumed_mid_sequence
```

## Considered and deferred (disclosed, not silently dropped)

Redesigning `_observe()`/`poll_once()` (the AUTO watcher path) to thread a
verified byte buffer through the same way REVIEW-006 R006-2 fixed the
MANUAL path was considered during R006-2's remediation and explicitly
deferred: the AUTO path's stability evidence is accumulated across
MULTIPLE watcher poll iterations (potentially across a watcher process
restart, via persisted `ingestion_state.json`), not a single synchronous
function call -- threading real content bytes through that persisted state
safely is a materially larger design change than the MANUAL path's fix,
and was not demonstrated as a live defect by either Codex review round (R006-2's
own finding named the MANUAL/manifest path specifically). Registered here
as a known, structurally-analogous, NOT-yet-demonstrated residual risk for
whichever wave addresses OPTION_B above, not something this pass silently
worked around.

## Answer to the M7 closure question this section exists to feed

`CODEX_ROUND_TRIP` capability-level qualification (has a full round trip
ever run live) is unaffected by this disposition -- three real round trips
have already occurred. What THIS section governs is narrower: whether the
CURRENT scope's known correctness gap is acceptable to carry into M7 sign-
off. That is recorded above as `HUMAN_DECISION_REQUIRED`, not resolved.
