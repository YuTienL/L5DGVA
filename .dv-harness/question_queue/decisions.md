# Decisions Log

Persisted answers to question-queue questions (dv_harness/question_queue.py, spec Part B). A question_key answered by a HUMAN and appearing here is resolved permanently: re-asking it self-resolves at Tier 1 instead of escalating again. A `tier2_auto_assumption` entry is only the harness's own provisional guess -- it is NOT an answer, and a later ask of the same question_key that trips a Tier-3 hard trigger still escalates for real. Regenerated in full from `.dv-harness/question_queue/decisions.json` on every write -- do not hand-edit; use `dv-harness question-queue revoke <question_key> --reason ...` to withdraw one.

## m7:r005-2-r006-4:legacy-unsealed-publication-risk-acceptance
- **Q-ID:** Q-ENV-7B9230FF
- **Domain / Owner:** env / DV-owner
- **Question:** Accept LEGACY_UNSEALED_PUBLICATION/COMPATIBILITY_MODE (R005-2/R006-4: default quiet-interval result-arrival inference, no sealed manifest by default) as sufficient for M7 sign-off, or block M7 pending a dedicated sealed-transport-contract wave?
- **Answer:** BLOCK_M7_PENDING_SEALED_TRANSPORT_WAVE
- **Basis:** tier2_safe_to_assume_default (worst case: one wasted, cheaply re-run regression)
- **Decided by:** dv_harness.question_queue(auto)
- **Decided at:** 2026-09-28T16:29:33.632518+00:00
- **Source:** tier2_auto_assumption
- **Ever a Tier-2 auto-assumption:** yes
- **Overturned a prior assumption:** no

## model_handoff:M7-V1-CHATGPT-ARCHITECTURE-REVIEW-001
- **Q-ID:** Q-ENV-CF3FB9CC
- **Domain / Owner:** env / DV-owner
- **Question:** Q-ENV-57D420FA: Project owner must choose ACCEPT_AS_NON_BLOCKING for LEGACY_UNSEALED_PUBLICATION/COMPATIBILITY_MODE, or BLOCK_M7_PENDING_SEALED_TRANSPORT_WAVE.
- **Answer:** request_correction
- **Basis:** tier2_safe_to_assume_default (worst case: one wasted, cheaply re-run regression)
- **Decided by:** dv_harness.question_queue(auto)
- **Decided at:** 2026-09-28T17:52:18.541840+00:00
- **Source:** tier2_auto_assumption
- **Ever a Tier-2 auto-assumption:** yes
- **Overturned a prior assumption:** no
