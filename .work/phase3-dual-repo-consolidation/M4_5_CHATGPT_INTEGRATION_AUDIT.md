# M4.5 — ChatGPT Integration Audit

```
CHATGPT_INTEGRATION = HUMAN_MEDIATED_CHATGPT_HANDOFF
```

## Real evidence

- `tools/migration/prepare_chatgpt_review.py:1-75` (Parent) — a real,
  runnable script. Reads `.migration/v50-to-v1/current-state.yaml`, copies
  that round's artifacts + `tools/migration/CHATGPT_REVIEW_CONTRACT.md`
  into `.chatgpt-handoff/<round>/`, writes `REVIEW_ME.md`. **No
  `openai`/`requests`/HTTP import anywhere in the file** — confirmed by
  the investigating agent's own grep. A human must open ChatGPT's own UI,
  paste the folder's contents, and manually copy results back.
- **Real observed output**: `.chatgpt-handoff/round2c/` exists on disk
  (dated 2026-09-09), matching the script's own copy list exactly
  (`CHATGPT_REVIEW_CONTRACT.md`, `CURRENT_STATE.yaml`, `REVIEW_ME.md`, 9
  `round2c-*.yaml/md` files) — proof the script was actually run at least
  once (`IMPLEMENTED` + `OBSERVED`).
- `tools/migration/CHATGPT_REVIEW_CONTRACT.md:1-44` defines ChatGPT's role
  as "Planner / Independent Gate Reviewer," requiring it to hand back a
  `NEXT_CODEX_PROMPT.md`. **Zero such file exists anywhere in either
  tree** — the loop's own return leg was never observed to complete even
  once.
- `.migration/v50-to-v1/current-state.yaml:12-14`: `current_round: ROUND2C`,
  `current_state: ROUND2C_COMPLETE_PENDING_CHATGPT_REVIEW`,
  `target.created: false` — the pipeline is stuck, stale since
  ~2026-09-09/10 (today is 2026-09-23), untracked in git, not referenced
  by the project's own current migration contract (`v1/CLAUDE.md` never
  mentions ChatGPT at all).
- `CODEX.md` (1575 lines) + `CODEX_V50_TO_V1_MIGRATION.md` — large,
  entirely prose "takeover contract" documents describing an aspirational
  Claude/Codex/ChatGPT/Human role model. **DOCUMENTED_ONLY** — no code in
  `dv_harness/` implements any dispatch logic from these documents; they
  are instructions meant for a human to load into a separate tool session.
- `codex/` and `chatgpt_version/` at Parent root are **full copies of the
  whole project tree** — organizational artifacts of a manual
  multi-checkout workflow (one checkout per external tool), not code.

## Operationalization

```
IMPLEMENTED = YES (prepare_chatgpt_review.py is real and runs)
WIRED = NO (no automatic invocation; a human runs the script by hand)
TRIGGERED = NO
CONSUMED = NO (ChatGPT's own output was never captured/consumed by any
               code -- the return leg, NEXT_CODEX_PROMPT.md, never exists)
OBSERVED = YES (round2c/ is real output of a real run)
TESTED = NO (no test file found exercising this script)
```

## Classification rationale

Per the strict HUMAN_MEDIATED-vs-AUTOMATED distinction: a human must
paste content into ChatGPT's UI and copy results back by hand at both
ends of this pipeline — there is no code path where the harness itself
calls out to ChatGPT or reads its response. This is real, useful tooling
(the staging half is genuinely automated file-copying, not literally
manual copy-paste of every file), but it does not qualify as
`AUTOMATED_CHATGPT_INTEGRATION`, which would require the harness itself
to invoke ChatGPT and consume its response without a human in the loop.

```
CHATGPT_OUTPUT_CONSUMED = NO
```

## Status

Stale/abandoned pipeline (last touched ~2 weeks before this audit, no
git tracking, superseded by the project's own current migration-track
CLAUDE.md which doesn't mention it). Not a live, current capability.
Recorded here as a real, disclosed finding for the Capability Superset
Matrix — not fixed, not revived, during M4.5.
