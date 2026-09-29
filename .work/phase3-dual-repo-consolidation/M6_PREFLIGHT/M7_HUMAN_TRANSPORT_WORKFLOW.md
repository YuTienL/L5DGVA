# M7 V1 -- Human Transport Workflow

Real, implemented UX: `dv_harness/model_handoff_workflow.execute_verb()`
(`python -m dv_harness.model_handoff_workflow export|import|status`).
Matches `model_agent_tool_router.py`'s own established precedent in this
repo: a standalone `python -m` front door, `cli.py`/`gates.py` not
touched (both disclosed as large files under heavy concurrent-edit
pressure).

## The real 5-step flow (architecture doc, "Human Transport Contract")

```
EXPORT HANDOFF            dv-harness-equivalent:
  |                       python -m dv_harness.model_handoff_workflow
  |                         export --task-id <id> --task-type <t>
  |                         --target-model codex|chatgpt ...
  v
HUMAN COPY/PASTE           (the ONLY manual step -- copy the printed
  |                         HANDOFF_GENERATED path's own file content)
  v
TARGET MODEL                (outside this harness's own tooling by
  |                         design -- M7 V1 scope)
  v
HUMAN RETURNS RESULT        (saves the target model's reply as a real
  |                         .md file, anywhere the human chooses)
  v
IMPORT RESULT               python -m dv_harness.model_handoff_workflow
                              import --task-id <id> --result-file <path>
```

Human responsibility is transport only -- the human never rewrites
scope, reinterprets evidence, merges model conclusions, or decides
whether a malformed result is valid (that is `model_result.
validate_result()`'s own job, never a human judgment call this workflow
delegates).

## Verbs

```
status --task-id <id> --root <dir> [--json]
  Reads current_state() -- a real, idempotent, non-mutating check. Never
  busy-waits: returns immediately with whatever the last real transition
  wrote.

export --task-id <id> --task-type <t> --target-model codex|chatgpt
       --project-id <p> --objective <o> --root <dir>
       [--allowed-files a,b] [--forbidden-files c,d]
       [--input-evidence-refs e,f] [--governance-trigger <phrase>]
       [--known-facts g,h] [--open-questions i,j]
       [--independence-requirement <text>]
       [--expected-output-type <type>] [--human-decision-required]
       [--json]
  Builds a real ModelHandoffV1 (build_handoff()), writes HANDOFF_V1.md
  + handoff.json to .dv-harness/model_handoffs/<task_id>/, transitions
  HANDOFF_READY -> WAITING_FOR_HUMAN_TRANSPORT, prints the real path and
  real handoff_bytes (a labeled proxy, never a token count).

import --task-id <id> --result-file <path> --root <dir> [--json]
  Runs the full Result Ingestion pipeline (M7_RESULT_INGESTION_AND_
  CONSUMPTION.md). Exit code 0 only when the result reached
  RESULT_CONSUMED; exit code 1 for any rejection (parse failure,
  validation failure, missing handoff) -- a real, checkable signal for
  a caller/CI, never a silent success.
```

## Real evidence this workflow works end-to-end

`test_valid_result_reaches_real_consumption` (full pipeline, PASS
result); `test_rejected_result_is_never_consumed` (full pipeline, a
mismatched result correctly stops before consumption);
`test_cli_export_then_status_round_trip` (the actual CLI entry point,
not just the underlying functions); `test_export_leaves_state_waiting_
for_human_transport` / `test_resume_reads_real_persisted_state_a_
second_process_could_read` (the resumability requirement, dispatch
section 9's own "must not busy-wait for the human").

## Real handoffs generated this task (genuinely WAITING_FOR_HUMAN_
TRANSPORT, not fabricated)

See `M7_CODEX_ROUND_TRIP_EVIDENCE.md` / `M7_CHATGPT_ROUND_TRIP_
EVIDENCE.md` for the two real handoff artifacts this task actually
exported against the live L5_DGVA repo (not a test fixture) --
`.dv-harness/model_handoffs/M7-V1-CODEX-REVIEW-001/HANDOFF_V1.md` and
`.dv-harness/model_handoffs/M7-V1-CHATGPT-DECISION-001/HANDOFF_V1.md`.
