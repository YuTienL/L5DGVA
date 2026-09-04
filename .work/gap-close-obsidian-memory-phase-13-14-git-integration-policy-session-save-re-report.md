# Phase 13 + 14 gap-close — Git Integration policy / Session Save-Restore (memory-specific)

**Verdict: DONE.** Both phases were audited READY, each with one explicitly
disclosed, real, closeable residual. Both residuals are now closed for real,
tested, and committed as `3d54424`.

**Test summary**: `114 passed` (test_react_inference_wiring +
test_memory_tier_integrity_and_admission + test_session_and_info +
test_debug_flow_memory), `259 passed` (test_knowledge_layer_git_and_duckdb +
test_engine_gates_and_routing + test_protocol_and_environment_mode_engine_wiring),
`218 passed` (test_memory_tier_completion, test_knowledge_center,
test_memory_vault, test_memory_write_guard_and_job_evidence,
test_obsidian_memory_final_integration, test_cli_memory_commands,
test_debug_flow_memory, test_memory_tier_integrity_and_admission,
test_react_working_memory_bridge); `python -m dv_harness.doc_citation_check` →
8 OK, 0 drifted, 0 unverifiable.

---

## 1. Re-confirmation of the audit's READY findings (no action taken)

Every cited item was independently re-checked against the current tree before
anything was changed. All held.

| Audit claim | Re-confirmed at |
|---|---|
| `_VAULT_WRITE_THROUGH_DESTINATIONS = {"JOB_MEMORY", "PROJECT_MEMORY"}`, WORKING_MEMORY excluded by construction | `memory_router.py:74`, consumed at `:234-238`; ENGINEERING at `:199-218`, ORGANIZATIONAL at `:181-185` (still gated on `push.get("ok")` first) |
| `memory(<protocol>): <desc>` commit message, `_general` only when genuinely absent | `_build_vault_commit_message()` — verified live by `test_knowledge_layer_git_and_duckdb.py` |
| Real `git rev-parse HEAD` SHA, never fabricated; written back as `knowledge_commit_sha` alongside `rtl_sha`/`tb_sha` | `memory_vault._commit_vault_change()`, `memory_router._write_back_knowledge_commit_sha()` (now at `:521-545`) |
| Phase 14's seven spec items (job/project/hypothesis/evidence/confidence/related memory/pending action) + `describe_resume_point()` | `session_snapshot.py` `save_session()` manifest block and `describe_resume_point()`; all seven still present and covered |
| Session snapshots never copy the durable Memory tier | `session_snapshot.py` module design comment — unchanged, and the Phase 14 fix below deliberately keeps it (references only, no bodies) |

Nothing in this list was modified except where the two residuals below
required it.

---

## 2. Phase 13 residual — CLOSED: `organizational_admission_gate()`

**The gap, as audited**: `ENGINEERING_MEMORY` is hard-gated by
`engineering_admission_gate()` before it can reach a store or a vault write.
`ORGANIZATIONAL_MEMORY` had no equivalent. `route_memory()` sent any record
with `kind ∈ {methodology, best_practice, cross_project_lesson}` and
`verified: true` straight to `OrganizationalMemoryStore.add()` — i.e. to the
**shared, cross-user** Knowledge Center — and, on a successful push, minted a
real vault git commit correctly labelled "Organizational Memory approval".
`promote_to_organizational()`'s three gates were enforced only by the fact
that its two real callers (`cli.py`'s `pmem_promote`, `engine.py:1925`) happen
to go through it.

**What was built** — `memory_router.organizational_admission_gate(root, record)`,
run first in the `ORGANIZATIONAL_MEMORY` branch of `route_and_store()`. It
mirrors `promote_to_organizational()`'s three gates and **re-reads two of them
from the durable store**, not from the payload asking to be admitted:

1. **Provenance + qualitative** — `source_engineering_memory_id` must resolve
   to a real ACTIVE engineering-tier record whose OWN `verification` block
   `_verification_is_gate_validated()` accepts (the same function the
   promotion path uses, not a looser copy). Reasons:
   `NO_ACTIVE_ENGINEERING_SOURCE_RECORD`, `QUALITATIVE_GATE_FAILED`.
2. **Repeated confirmation** — that source record's **on-disk**
   `confirmation_count` must be `>= ORGANIZATIONAL_MIN_CONFIRMATIONS`. Because
   `MemoryStore._apply_confirmation_integrity()` discards a payload-supplied
   count and only `MemoryGC.confirm()` can advance it, this gate is not
   forgeable. Reason: `INSUFFICIENT_CONFIRMATION`.
3. **Confidence** — `confidence_result["level"] == "HIGH"`. Reason:
   `CONFIDENCE_NOT_HIGH`.

Reason codes deliberately reuse `promote_to_organizational()`'s own strings so
the two paths speak one vocabulary.

**Rejection behaviour**: demotion to Working Memory carrying
`organizational_admission_rejected` and `requested_destination`, exactly the
contract `engineering_admission_gate()` already uses — never a raise, never a
drop. Since `WORKING_MEMORY` is excluded from
`_VAULT_WRITE_THROUGH_DESTINATIONS`, that demotion is also what makes "no
unearned Organizational-approval commit" structurally true rather than a
separate check.

**Disclosed limitation, stated in the code and in
`docs/MEMORY_ARCHITECTURE.md`**: gate 3 is checked as *stamped*, not
recomputed. `score_confidence()`'s inputs (`independent_sources_count` etc.)
exist only at promotion time and are not persisted on the source engineering
record, so there is nothing to re-derive from. Gates 1 and 2 — the ones that
were actually forgeable — are store-backed.

**Tests** (new section 5 of `dv_harness_tests/test_memory_tier_integrity_and_admission.py`,
7 cases):
- the shared broker is **never contacted** (`OrganizationalMemoryStore` not
  even constructed) for an ungated record;
- the demoted record is readable in Working Memory with its reason codes;
- **no vault note is written** for a rejected record (Phase 13's commit policy);
- a payload declaring `source_confirmation_count = 7` against a source with 0
  real confirmations is refused → `INSUFFICIENT_CONFIRMATION`;
- provenance pointing at a source with two real confirmations but no
  gate-validated verification block is refused → `QUALITATIVE_GATE_FAILED`,
  even when the *promoted* record carries a valid-looking block;
- retracting the source record re-closes an otherwise-passing gate;
- the earned `promote_to_organizational()` path still clears the boundary,
  asserted at the real push.

**Existing tests updated, not weakened**: four modules
(`test_memory_tier_completion`, `test_knowledge_center`, `test_memory_vault`,
`test_memory_write_guard_and_job_evidence`) exercise what happens *after* this
boundary, so they now build their record through one shared new helper,
`dv_harness_tests/organizational_promotion_fixture.py`, which seeds a real
engineering source record with two real `MemoryGC.confirm()` calls and a real
`score_confidence()` result. Without it those tests would have silently become
tests of the WORKING_MEMORY path — that risk is called out in
`test_memory_write_guard_and_job_evidence.py`'s own helper docstring, and its
now-stale class docstring ("reachable directly") was corrected.

---

## 3. Phase 14 residual — CLOSED: `related_memory` is now the real one

**The gap, as audited**: `related_memory` was a `MemoryRetriever.search()`
**re-run at save time** over `stage + project + note`. The real per-stage
memory context (`relevant_memory`, `vault_related_cases`, `kc_search_results`)
was built fresh inside `_gather_stage_context()` on every `run_stage()` call,
folded into the prompt and then discarded — so there was no ground truth for
the snapshot to read. The engine searches on `stage + user_goal` and also
consults the Vault and the shared Knowledge Center, so the two can genuinely
disagree, and a resumed session could not tell which it was looking at.

**What was built**:
- `react.build_memory_context_references()` — a **references-only** projection
  of the three real lists (local hits keep the same five keys
  `session_snapshot`'s own reference shape uses; vault/evidence-DB cases keep
  `note_id`/`path`/`protocol`/`score`/`source`; KC hits keep
  `memory_id`/`title`/`protocol`). Never a record body — `iteration_NNN.json`
  is copied wholesale into every snapshot, so a body there would duplicate the
  durable Memory tier into the snapshot, which this module's own design
  forbids. An empty result is `{}`, not a dict of empty lists, so "nothing was
  in play" and "this attempt predates the field" stay distinguishable.
- `ReactRecorder.record(..., memory_context=...)` persists it onto the same
  `iteration_NNN.json` and its Working Memory projection every other field of
  that record already uses. Optional, defaults to `None` — every pre-existing
  caller is unaffected.
- `engine.run_stage()` supplies it from `ctx["relevant_memory"]` /
  `ctx["kc_search_results"]` / `ctx["vault_related_cases"]` — the exact three
  lists it had already folded into the prompt.
- `session_snapshot._resolve_related_memory_references()` **prefers** the
  recorded context, falls back to the recompute, and records which in a new
  manifest field `related_memory_source`
  (`react_iteration_memory_context` / `recomputed_at_save_time` / `none`). The
  stage's vault/KC half survives into the manifest too instead of being
  flattened away. `describe_resume_point()` now *states* the provenance in
  words ("the memory this stage really consulted" vs. "re-searched at save
  time, may differ from what the stage consulted").

**Tests** (5 new in `test_session_and_info.py`, 1 in
`test_react_inference_wiring.py`):
- the recorded and recomputed answers are made to genuinely **differ**, and
  the manifest is asserted to carry the recorded one while a live
  `_collect_related_memory_references()` call is asserted to return the other
  — so this is not a test that would pass under the old behaviour;
- fallback path is labelled `recomputed_at_save_time`, and a project with no
  memory activity reports `none` rather than a misleading label;
- the persisted `memory_context` carries references only, proven against a
  source record that really does carry more (`evidence` present on the record,
  absent from the reference);
- the resume summary states provenance, both ways;
- **wiring proof**: a real `DVHarness.run_stage()` over the real graph and
  real gate scripts, with a memory record seeded beforehand, and the assertion
  read off the real persisted `iteration_001.json` plus its Working Memory
  twin — not a hand-written fixture file.

---

## 4. Docs / policy updated (no stale claims left behind)

- `CLAUDE.md` — Engineering Memory Policy: "ONLY through
  `promote_to_organizational()`" is now stated as **enforced at the write
  boundary** rather than trusted from callers.
- `docs/MEMORY_ARCHITECTURE.md` — new "The admission gate" subsection (all
  three gates, reason codes, the demotion contract, the disclosed limitation);
  corrected the now-false "reachable from a plain `route_and_store()` call"
  sentence in the write-guard section; two drifted `file.py:line` citations
  re-pointed (`doc_citation_check` back to 8 OK / 0 drifted).
- `docs/MEMORY_SCHEMA.md` — routing table row for `ORGANIZATIONAL_MEMORY`.
- `docs/MEMORY_OPERATIONS.md` — commit-policy paragraph now notes both
  admission gates run before a commit can be minted.
- `docs/ENGINE_STAGE_LIFECYCLE.md` — the three memory rows of
  `_gather_stage_context()` are read-only but no longer transient.
- `.claude/skills/CORE/organizational-memory/SKILL.md` — "never write
  ORGANIZATIONAL_MEMORY directly" is now "and you cannot"; the **Fallback**
  section states that hand-constructing a record is not a workaround and why.
- `.claude/skills/EXPERT_FEEDBACK/knowledge-promotion-gate/SKILL.md`,
  `.claude/agents/memory-agent.md`, `docs/MEMORY_AGENT.md` — read and found
  already correct ("never straight to Organizational", "promote_to_organizational() ONLY");
  no edit needed.

## 5. Concurrency / commit handling

Other workflows were committing into this repo throughout. `CLAUDE.md` was
hand-scoped (`git diff` → trim to my single hunk → `git apply --cached --check`
→ `--cached`) rather than `git add`ed, twice: a concurrent
`protocol-capability` commit landed a separate 61-line `CLAUDE.md` section
between my first staging and my commit, and swept my staged hunk out of the
index in the process. The final commit `3d54424` carries exactly my 18 files
and none of any other workflow's. `dv_harness/engine.py` was checked for
foreign hunks before staging (a concurrent waveform-gate change had already
been committed as `b20e038`, leaving my diff clean).

One self-inflicted defect, corrected: the first commit attempt used a
PowerShell here-string in a bash heredoc, which produced a commit with a
mangled subject and truncated body. It was amended in place (still tip, still
unpushed, verified `HEAD` had not moved) into `3d54424` with the full message
and the CLAUDE.md hunk included.

No push, no merge to a protected branch — per this repo's
gh-CLI/PR-only governance policy.
