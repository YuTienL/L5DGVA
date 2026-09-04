# Gap-Close Pass — Phase 6 + Phase 10 (Inference Engine integration + Debug Flow mechanics)

**Result: NO_ACTION_NEEDED**

Scope: the user's 25-phase structural spec, Phase 6 (Autonomous Inference Engine
integration) and Phase 10 (Debug Flow mechanics). The incoming audit marked both
**READY** with zero BLOCKED and zero PARTIAL sub-items. Per this pass's own rules,
READY sub-items get re-confirmed, not rebuilt. Every cited claim below was
re-verified independently in this pass against the current working tree — no file
was modified, nothing was built, nothing was committed beyond this report.

`dv_harness/engine.py` carries uncommitted edits from concurrently-running
workflows, so every engine claim was re-located by `grep` rather than trusted at
its originally-cited line number. The re-located line numbers are recorded below;
where they differ from the audit's, the audit's numbers were stale by a few lines,
not wrong about the mechanism.

---

## Phase 6 — Autonomous Inference Engine Integration — READY (re-confirmed)

| Claim | Re-verified at | Status |
|---|---|---|
| `score_confidence()` implements the documented formula incl. HIGH-safety-floor cap | `dv_harness/inference.py:25-64` | confirmed |
| `identify_gap()` is a pure ordered set difference | `dv_harness/inference.py:67-82` | confirmed |
| `promote_if_high_confidence()` gates on `level=="HIGH"` and on `kc_client.add()`'s own `ok` | `dv_harness/inference.py:108-133` | confirmed |
| `next_best_action()` cross-references the real `protocol_builder_registry.json` | `dv_harness/inference.py:136-178` | confirmed |
| Before-debug memory search gated to FAILURE_RECOVERY/RE_AUDIT only | `dv_harness/engine.py:2502` | confirmed |
| Signature built from real Blackboard `findings.last_report` + `route_info.protocol_decision` | `dv_harness/engine.py:2504-2514` | confirmed |
| Results folded into the real stage prompt | `dv_harness/engine.py:2534` → `dv_harness/prompts.py:2940-2947` | confirmed |
| Per-attempt Hypothesis→Evidence→Confidence→Gap→Next-Best-Action is real computation | `dv_harness/engine.py:1269-1370`, called at `:3416-3421` | confirmed |
| Root-cause confidence scored off cited evidence, never self-reported | `dv_harness/engine.py:1372-1519`, called at `:3263` | confirmed |

Two points worth recording because they are the exact failure classes the spec
warns about, and both hold:

1. **Not importable-but-uncalled.** `engine.py:14-16` imports
   `build_failure_signature`/`search_related_memory_for_debug`,
   `score_confidence`/`identify_gap`/`next_best_action`/`promote_if_high_confidence`,
   and `promote_to_organizational`, and every one has a real call site in
   `run_stage()`'s control flow (grep output above).
2. **The "prior knowledge, not current answer" rule is in the wire, not a comment.**
   `prompts.py:2941-2945` injects, verbatim, into the prompt actually sent to the
   LLM: `依 CLAUDE.md Evidence Truth Rule，current evidence 永遠優先於這裡任何一筆記錄；
   不得直接假設 previous root cause == current root cause，目前 RTL/VIP/log/waveform
   證據仍須獨立重新驗證`.

---

## Phase 10 — Debug Flow Mechanics — READY (re-confirmed)

**Before Debug (all six):**

1. Capture failure signature — `memory_vault.py:1186` `build_failure_signature()`, called `engine.py:2511-2514`.
2. Search related memory — `memory_vault.py:1338` `search_related_memory_for_debug()`, called `engine.py:2515-2516`; merges Vault Markdown notes with the Evidence-Layer DuckDB `failure_signatures` table (`search_evidence_db_failure_signatures()`, `memory_vault.py:1232`).
3. Rank related cases — see the dedicated check below.
4. Present prior evidence — `engine.py:2534` → `prompts.py:2940-2947`, disclaimed.
5. Generate hypotheses — agent's `root_cause_evidence_gate.hypotheses`, independently re-scored.
6. Validate against current environment — `_score_root_cause_confidence()` (`engine.py:1372-1519`) recomputes `independent_sources_count` / `evidence_refs_verified` / `counter_evidence_count` from the same evidence block's real citations (`:1395-1412` documents and implements exactly this), never `block.get("confidence")`.

**During Debug:** per-attempt inference loop, `engine.py:1269-1370` / `:3416-3421`.

**After Debug — both branches real and mutually exclusive by gate id:**

- FAIL/PARTIAL → Job Memory only. `engine.py:3393-3395` gates on
  `stage in (FAILURE_RECOVERY, RE_AUDIT) and ss["status"] in (FAIL, PARTIAL)`
  and calls `_record_debug_attempt_job_memory()` (`:1934-1975`), which stores
  `kind="job_failure"` — the docstring at `:1944-1948` states outright that it
  never uses `kind="root_cause"/"verified_fix"/"debug_lesson"` because those
  route to ENGINEERING_MEMORY and would trigger promotion on an unverified
  attempt. WAIT_USER / NEEDS_USER_INPUT deliberately excluded.
- RE_AUDIT PASS → record + trigger promotion evaluation. `engine.py:3263` then
  `:3267` (`_score_root_cause_confidence` → `_promote_verified_fix_knowledge`),
  reaching the real 3-gate `promote_to_organizational()`
  (`memory_router.py:445`; gate 2 calls the same `inference.score_confidence` at
  `:501/:516`, gate 3 checks `ORGANIZATIONAL_MIN_CONFIRMATIONS = 2` at `:15/:521`,
  returning `INSUFFICIENT_CONFIRMATION` at `:523`). "Triggers, not always
  succeeds" is honest: a first PASS legitimately returns
  `INSUFFICIENT_CONFIRMATION`, which is the spec's intent, not a defect.

**Extra check performed this pass (the audit's softest claim — item 3, "ranked on
one common scale"):** verified rather than accepted. The two sources genuinely
share a scale:

- Evidence-DB side, `memory_vault.py:1313-1318`: `score = 3.0 if protocol else 0.0`, then `+= len(q_tokens & _tokenize(haystack))`.
- Vault-adapter side, `memory_vault.py:764-772`: `score += 3.0 * <matching property_filters>` (protocol is passed as a property filter), then `+= len(q_tokens & _tokenize(haystack)) * 1.0` — via the *same* `_tokenize` imported from `memory.py`.

Same 3.0 protocol weight, same 1.0-per-shared-token weight, same tokenizer — so
the single merged `sorted(..., key=lambda c: -float(c.get("score") or 0.0))` at
`memory_vault.py:1411-1412` is a real ranking, not two incomparable lists
concatenated.

**Shared interface, other side:** `lsf_client.py:926`
`_write_job_tier_memory_on_terminal_reconcile()` calls the same
`build_failure_signature()` / `search_related_memory_for_debug()` at `:1200-1214`,
invoked from reconcile at `:1245` — one debug-flow mechanism, two callers, not a
duplicate implementation.

---

## Test evidence (live run this pass)

```
python -m pytest dv_harness_tests/test_debug_flow_memory.py \
                 dv_harness_tests/test_inference_engine_wiring.py -q
30 passed in 178.06s (0:02:58)
```

18 debug-flow + 12 inference-wiring tests. The end-to-end ones drive real
`DVHarness(tmp).run_stage(...)` rather than isolated unit calls — notably
`test_failure_recovery_partial_attempt_writes_job_memory_only_never_engineering_memory`,
`test_re_audit_pass_writes_no_job_memory_record_only_engineering`,
`test_re_audit_pass_triggers_the_real_organizational_promotion_evaluation`, and
`test_terminal_reconcile_memory_search_failure_never_blocks_the_job_memory_write`.

---

## Changes made

None. No BLOCKED item to close and no boundable PARTIAL item to complete within
this scope. No source file was modified; no stale comment or dead code was found
in the code paths inspected. This report is the only artifact produced.
