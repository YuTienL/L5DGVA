# M7 REVIEW-003 Live Ingestion Evidence

Live qualification case: `TASK_ID=M7-V1-CODEX-REVIEW-003`,
`EXPECTED_RESULT_FILE=.dv-harness/model_handoffs/M7-V1-CODEX-REVIEW-003/RESULT_V1.md`.

## What happened (real timestamps, local +08:00)

| Time | Event | Source |
|---|---|---|
| 21:06:41 | HANDOFF_V1.md generated, `WAITING_FOR_HUMAN_TRANSPORT` | `export` (previous task) |
| 21:23:05 | **Real Codex `RESULT_V1.md` appears at the expected path** (file mtime) | human transport, not by this agent |
| 21:35:14 | Startup scan begins: task auto-registered from its persisted wait state, `RESULT_DETECTED` (size 10854, sha256 `484b535b90c6298e4a28079ceae1eb8039b885ec9dfa6df7a9298a2947bc42c4`) | `python -m dv_harness.result_ingestion scan` |
| 21:35:16.097 | `RESULT_STABILITY_CONFIRMED` (3 observations over the 2.0 s quiet interval) | `ingestion_events.jsonl` |
| 21:35:16.101 | `RESULT_HASHED` -> `AUTO_IMPORT_STARTED` (`import_attempt_id=M7-V1-CODEX-REVIEW-003:484b535b90c6:0686b084`) | same |
| 21:35:16.269-.270 | `RESULT_ACCEPTED`, `RESULT_CONSUMED` (canonical `import_result()`, all validators) | same |
| 21:35:16.278-.281 | `AUTO_RESUME_STARTED`, `NEXT_ACTION_RESOLVED = AUTO_REMEDIATE_CONFIRMED_FINDINGS` (`HUMAN_ACTION_REQUIRED=NO`) | same |

The result file is byte-identical to what arrived (sha256 verified again
after ingestion and after the remediation commit); it was never edited,
normalized or re-saved.

## Qualification verdict, stated precisely

- `REVIEW_003_LIVE_QUALIFICATION=PASS_VIA_STARTUP_SCAN`: a real external
  result, unmodified, went detected -> stable -> hashed -> imported ->
  validated -> consumed -> persisted -> resumed -> next action resolved with
  no `import` command invoked by anyone.
- `MANUAL_IMPORT_COMMAND_USED_FOR_LIVE_QUALIFICATION=NO`. The trigger was the
  startup-scan front door, run by this agent session as a normal resume step;
  the human's only act was placing the file.
- Not claimed: the detached watcher *process* did not perform this ingestion.
  The result had already arrived before the watcher was started, so this was
  the STARTUP_PENDING_RESULT_SCAN path (which the requirements say correctness
  must not depend on the watcher for). The watcher process itself was
  qualified end to end on a clearly synthetic task in a throwaway repo
  (`M7_WATCHER_RECOVERY_EVIDENCE.md`: 2.0 s from file placement to consumed,
  no import command) and is armed for REVIEW-004 (below), whose arrival will be
  the first live watcher-process qualification.

## Two things this run got wrong, disclosed

1. After the ingestion I ran a hand-written status script that overwrote the
   task's persisted stop record with misleading text (an old "transport" next
   step, empty resume action). Found on inspection, repaired from the real
   `next_action.json`, and `resume_after_import()` is the only code that should
   write that record. No decision was affected.
2. The scan also auto-registered `M7-V1-CHATGPT-DECISION-001` (a pre-existing
   handoff waiting for transport). It is only being *watched*; no ChatGPT
   round trip was started.

## Outcome of the ingested result

`RESULT_STATUS=FAIL`, `HUMAN_DECISION_REQUIRED=NO`, findings N1-N6 (N1
CRITICAL). Routed by the contract to autonomous remediation:
see `M7_CODEX_REVIEW_003_FINDINGS_REMEDIATION_REPORT.md`.
