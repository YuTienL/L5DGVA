# M7 Provider Independence Qualification

Per the M7 Convergence prompt, section 13.

## Claim under test

Codex and ChatGPT results both traverse
`PARSE -> VALIDATE -> CONSUME -> CLASSIFY -> NEXT_ACTION` without
provider-specific orchestration forks beyond transport/backend adapters.

## Real evidence

``` text
CODEX_PATH  = LIVE_QUALIFIED (4 real round trips: REVIEW-003/004/005/006,
              each through model_handoff_workflow.import_result() ->
              result_ingestion.ingest_result_file(), zero manual
              intervention on the consumption side)
CHATGPT_PATH = STRUCTURALLY_READY, NOT_LIVE_QUALIFIED (no real ChatGPT
              result has ever been consumed; see
              M7_CHATGPT_RESULT_CONSUMPTION_EVIDENCE.md)
```

Grep evidence that the pipeline itself never branches on producer/target
model (checked across every function in the real consumption chain):

``` text
dv_harness/model_handoff_workflow.py:  import_result(), _import_result_inner(),
  _consume_result(), _append_registry() -- no `if ... == "codex"` /
  `== "chatgpt"` branch anywhere in any of these.
dv_harness/result_ingestion.py:        ingest_result_file(), _ingest_locked(),
  _observe(), poll_once() -- same: dispatch is on task_id/content only.
```

`PRODUCER_MODEL`/`TARGET_MODEL` are carried as DATA fields
(`ModelResultV1.producer_model`, `ModelHandoffV1.target_model`) used for
audit/registry/routing bookkeeping (which directory, which registry row),
never as a control-flow discriminant inside the parse/validate/consume/
classify chain itself.

## Disposition

``` text
PROVIDER_INDEPENDENCE = PARTIALLY_LIVE_QUALIFIED
```

The pipeline's provider-agnostic STRUCTURE is real and verified by direct
code inspection (not merely asserted). Full `LIVE_QUALIFIED` status
requires an actual ChatGPT round trip to have completed through the SAME
pipeline, which has not yet happened (blocked behind Codex branch closure
per this program's own required ordering, not a provider-independence
defect). This is a real, honest, narrower-than-"fully qualified" status --
disclosed rather than rounded up.
