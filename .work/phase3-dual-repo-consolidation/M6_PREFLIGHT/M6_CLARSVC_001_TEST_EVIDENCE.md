# CAP-M6-CLARSVC-001 — Test Evidence

## New test file: `dv_harness_tests/test_clarification_service.py` — 13/13 pass

Every required family from this capability's own dispatch (item 23), each
mapped to a real, passing test:

| Required family | Test(s) | Result |
|---|---|---|
| No-question auto-discovery path | `test_no_question_when_automatically_resolved`, `test_optional_field_never_asks_even_when_unresolved` | PASS |
| Unresolved-question path | `test_unresolved_required_field_files_a_real_question` | PASS |
| DE owner | `test_de_question_owner_is_design_for_a_dut_domain_field` | PASS |
| DV owner | `test_dv_question_owner_is_verification_for_env_and_vip_domain_fields` | PASS |
| SHARED owner | `test_shared_question_owner_only_for_a_genuine_dut_conflict`, `test_an_ordinary_unknown_dut_field_is_not_automatically_shared` | PASS |
| Conflicting candidates | `test_conflict_preserves_both_evidence_backed_candidates_never_silently_chooses` | PASS |
| Answer round-trip | `test_answer_round_trip_feeds_back_through_field_resolution` | PASS |
| Answer re-validation / still-unresolved answer | `test_still_unresolved_after_an_empty_or_insufficient_answer` | PASS |
| Duplicate question suppression | `test_duplicate_question_is_not_re_filed_without_evidence_change` | PASS |
| Dispatch blocking / resume | `test_dispatch_blocks_on_unresolved_field_and_resumes_after_answer` | PASS |
| HumanGate state projection | `test_human_gate_state_projects_real_question_queue_status` | PASS |

CLI/dashboard compatibility is not re-tested in this file — it is already
covered by `test_start_lifecycle_dispatch.py`'s own `test_cli_start_
converges_on_start_lifecycle_not_direct_loop_or_run_stage` / `test_
dashboard_start_background_run_converges_on_start_lifecycle`, both of which
still exercise the real `start_lifecycle()` path (now internally delegating
to `clarification_service.resolve_or_ask()`), re-run and confirmed passing
below.

## Focused regression across every directly-touched module — 268/268 pass

```
python -m pytest
  dv_harness_tests/test_question_queue.py
  dv_harness_tests/test_intake_field_resolution.py
  dv_harness_tests/test_clarification_service.py
  dv_harness_tests/test_start_lifecycle_dispatch.py
  dv_harness_tests/test_intake_state.py -q
=> 268 passed in 8.62s
```

`test_question_queue.py` (166) and `test_intake_field_resolution.py` (25)
confirm the additive `authority_role` schema/parameter change broke nothing.
`test_start_lifecycle_dispatch.py` (23) confirms the `start_lifecycle()`
refactor (delegating to `clarification_service.resolve_or_ask()` instead of
re-inlining the same logic) preserved every previously-tested behavior.
`test_intake_state.py` confirms the deliberate decision to leave that module
unmerged did not disturb it.

## Broad regression — same 47-file dispatch-caller population + this capability's own new test file

```
python -m pytest <47 dispatch-caller files> dv_harness_tests/test_clarification_service.py -v
```

Watched continuously with real per-test hang discipline (no test name
repeated across consecutive polls without CPU-activity confirmation, per
this task's own explicit instruction not to use CPU usage alone as a hang
heuristic — every "still on the same test" observation was cross-checked
against either elapsed time matching that test's own known historical
duration, or a live CPU-accumulation check, before being judged healthy
rather than hung).

Two individually-verified real end-to-end paths through the refactored
`start_lifecycle()`/`run_stage()`: `test_dashboard_interactive.py::test_
start_loop_true_advances_through_multiple_stages_in_background` (dashboard's
own real multi-stage background run) — confirmed PASS, identical to its
result in the `CAP-M6-DISPATCH-001` regression, proving the `clarification_
service` refactor changed no observable dashboard behavior for a project
with no declared `field_controls`.

See `M6_CLARSVC_001_IMPLEMENTATION_REPORT.md` for the final aggregate
counts and failure-identity comparison against the `CAP-M6-DISPATCH-001`
regression's own already-classified 5 pre-existing failures.
