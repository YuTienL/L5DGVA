# M6 Final Operational Slice Qualification -- Failure Path Qualification

Every representative failure class this task's own section 17 names,
evaluated against the current, frozen candidate tree. Each row: failure
detected? correct layer owns it? false PASS? evidence retained? no
uncontrolled continuation?

| Failure class | Applicable to M6? | Detected by | Owning layer | Evidence retained | Continuation |
|---|---|---|---|---|---|
| Invalid protocol | **NOT_APPLICABLE_WITH_EVIDENCE** -- `protocol_field_control()`'s own validator is `None` (bare non-blank check only); protocol vocabulary is genuinely open (any protocol name is legal), by design (`generation_field_controls.py`'s own module docstring: a generic slot over protocol-specific vocabulary) -- no format constraint exists to violate | n/a | n/a | n/a | n/a |
| Invalid DUT role | **NOT_APPLICABLE_WITH_EVIDENCE** -- same reasoning; `role_field_control()`'s validator is also `None` | n/a | n/a | n/a | n/a |
| Invalid verification level | **APPLICABLE, QUALIFIED** | `_verification_level_validator()` (Field Resolution) rejects a non-spelling at the CLARIFICATION layer; `environment_mode_router._resolve_with_level()`'s own `INVALID_VERIFICATION_LEVEL` rejects at the ROUTING layer (defense in depth, both real) | Field Resolution (primary); VerificationLevel routing (secondary, unreachable in practice since Field Resolution already rejects first) | Yes -- `ValidationState.INVALID` + reason string; router's own `reason`/`evidence` fields | No false PASS; the field simply never resolves | `test_invalid_declaration_is_reported_not_guessed`-equivalent coverage: `test_invalid_verification_level_spelling_is_unresolved_not_guessed` (router level) |
| Missing required field | **APPLICABLE, QUALIFIED** | `resolve_field()`'s own required-field check | Field Resolution / HumanGate | Yes -- a real, persisted question | No false PASS; `blocked_by=clarification`, generation never runs | `test_all_three_unresolved_files_three_real_questions`, `test_no_declared_protocol_and_no_prior_fact_files_a_real_unresolved_question`, `test_no_declared_role_and_no_prior_fact_files_a_real_unresolved_question` |
| Conflicting field evidence | **APPLICABLE (mechanism level), QUALIFIED** -- proven at the SHARED `intake_field_resolution.resolve_field()` engine M6's own 3 fields unconditionally reuse (no M6-specific special-casing exists to diverge, confirmed by direct source read of `generation_field_controls.py`) | `resolve_field()`'s own conflict detection | Field Resolution | Yes -- both evidence-backed candidates preserved, never silently chosen | No false PASS; a real question, not a silent pick | `test_declared_versus_discovered_conflict_is_contradicted_never_silently_overwritten`, `test_a_conflict_with_more_than_three_sides_is_refused_rather_than_truncated`, `test_conflict_preserves_both_evidence_backed_candidates_never_silently_chooses` |
| Task Boundary rejection | **APPLICABLE, QUALIFIED** | `task_boundary_conformance.check_working_tree_conformance()` | Task Boundary (stage 8) | Yes -- a real `TASK_BOUNDARY_BLOCKED` event + `findings` | No false PASS; VerificationLevel/generation never reached | `test_m6_task_boundary_production_001.py`'s 6 FAIL-path tests (CLI/dashboard/all 3 levels/forbidden-nested-under-allowed) |
| Generation failure | **APPLICABLE, QUALIFIED** | `create_environment()`'s own 10 real documented exception classes | GENERATION_CONSUMER, normalized at the `start_lifecycle()` boundary | Yes -- a real `AgentResult(ok=False, raw={"blocked_by": "generation", "error":..., "status":..., "detail":...})`, never an uncaught exception | No false PASS | `test_generation_failure_is_a_real_agent_result_not_an_uncaught_exception` (re-verified this task, see `M6_FINAL_EVIDENCE_CHAIN_QUALIFICATION.md`'s generation-failure-normalization section) |
| Unsupported/invalid topology | **APPLICABLE, QUALIFIED** | `protocol_model_layer.py`'s own topology validator | GENERATION_CONSUMER (the protocol model layer, which runs BEFORE the skeleton is written) | Yes -- `ProtocolModelLayerError`, `PROTOCOL_MODEL_TOPOLOGY_REJECTED`, `model_reason` (e.g. `INVALID_LANE_WIDTH`) | No false PASS; the model runs before the skeleton, so a refusal leaves nothing written (`assert not (root / "out" / "tb").exists()`) | `test_a_rejected_protocol_model_topology_returns_a_real_agent_result_not_an_uncaught_exception` |

## Summary

```
FAILURE_PATH_VALIDATED (applicable classes) = 5/5 QUALIFIED
  (invalid verification level; missing required field; conflicting field
  evidence; Task Boundary rejection; generation failure incl. invalid
  topology)
NOT_APPLICABLE_WITH_EVIDENCE = 2 (invalid protocol; invalid DUT role --
  no format constraint exists by design, not an oversight)
```

No uncontrolled continuation found in any applicable class: every
failure either files a real, persisted question (Field Resolution
layer) or returns a real, structured `AgentResult(ok=False, ...)` (Task
Boundary / generation layers) -- never an uncaught exception, never a
silent false PASS.
