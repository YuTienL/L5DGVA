# Autonomous Gate Self-Tuning — Design

## Goal

DV Agent Harness L5 currently has no mechanism by which its own verification
rules (gate thresholds, which gates apply to which stage, whether a gate is
enabled) improve from accumulated real execution experience without a human
or Claude engineering session manually editing source and committing. This
spec adds that mechanism: a **confidence/risk-gated autonomous tuning loop**
that, by default, requires no human action to take effect, but automatically
defers to a human whenever its own analysis is uncertain or the proposed
change is inherently higher-risk.

This is explicitly **not** general machine learning — no model weights, no
neural network. It is a structured, evidence-driven, LLM-assisted process
that mines real execution history for patterns and safely edits a small,
externalized configuration surface. See "Non-goals" below for what this
deliberately does not do.

## Global Constraints

- Self-tuning may **only** ever write to two JSON files under
  `.dv-harness/self_tuning/` (`parameters.json`, `stage_gate_overrides.json`)
  plus its own append-only history/state files. It must **never** modify any
  `.py` source file, `gates.py`'s `STAGE_GATES` dict literal, or
  `engine.py`'s control flow. This is the single architectural invariant
  the rest of the safety model depends on.
- A fixed, hardcoded (Python-source, not JSON-configurable) protected list
  denies removal of specific gates from specific stages and denies exposing
  specific parameters as tunable, regardless of what any analysis proposes.
  See "Safety boundary."
- Every adjustment (auto-applied or human-approved) is written to
  Engineering Memory (`kind="self_tuning_adjustment"`) with full before/
  after values and the evidence that triggered it, and is revertible via a
  single CLI command.
- Default: every existing gate is a *candidate* for tunability (per the
  user's explicit choice — no per-gate opt-in allowlist), constrained only
  by the protected list above. Rolling every existing gate script over to
  expose `get_param()`-based values is a large, separate, mechanical
  follow-up (see "Rollout plan") — this spec's initial implementation
  covers the mechanism plus a first batch of gates, not all 60+ at once.

---

## Architecture

Four components:

### 1. Tunable-parameter layer

`.dv-harness/self_tuning/parameters.json`:
```json
{
  "<gate_id>": { "<param_name>": <value>, ... }
}
```
New module `dv_harness/self_tuning.py` exposes:
```python
def get_param(root: Path, gate_id: str, name: str, default: Any) -> Any
```
A gate script that wants a value to be tunable calls this instead of using a
hardcoded literal, falling back to `default` (today's hardcoded value)
when unset. This is how a gate "opts in" at the code level, but per the
Global Constraints, **which** gates get this treatment is decided by
project policy (default: all, minus the protected list), not by each gate
script author choosing individually.

### 2. Stage-gate membership overlay

`.dv-harness/self_tuning/stage_gate_overrides.json`:
```json
{
  "<STAGE>": { "add": ["<gate_id>", ...], "remove": ["<gate_id>", ...] }
}
```
`dv_harness/gates.py` gains:
```python
def effective_stage_gates(stage: str, root: Path) -> list
```
which starts from the existing hardcoded `STAGE_GATES[stage]` and applies
the overlay, with the protected list enforced *inside this function itself*
(a `remove` entry naming a protected gate_id is silently ignored, not
merely discouraged) — so the invariant holds even if the overlay file is
somehow hand-edited outside the tuning loop.

### 3. Retrospective review cycle (the actual "tuning")

**Trigger**: `.dv-harness/self_tuning/state.json` tracks
`executions_since_last_review`, incremented once per real `run_stage()`
call that reaches a terminal verdict (PASS/GATE_FAIL/ADAPTER_FAIL — not
NO_GATE_REQUIRED trivial stages). Default `N = 20` (configurable in
`.dv-harness/config.json`'s new `self_tuning.review_every_n_executions`).
When the counter reaches `N`, a review runs **inline** at the end of that
`run_stage()` call — no new background daemon, matching the existing
`_promote_verified_fix_knowledge`-style inline-call pattern rather than
introducing LSF-watcher-style process complexity.

**Evidence assembled for the review**:
- `gate_history.jsonl` (new, append-only, written by `run_gate()` on every
  real gate invocation since the last review: `{gate_id, stage, verdict,
  reason, timestamp}`).
- Human `dv-harness correct <stage> --note` records already persisted via
  `ControlPlane` (mined for "a human said this gate's verdict here was
  wrong" signal).
- Current `parameters.json`/`stage_gate_overrides.json` contents (so the
  analysis knows what's already been tuned, to detect thrashing).
- Adjustment history (so a gate reverted last cycle is flagged, not
  re-proposed identically).

**Analysis**: dispatched through the *same* `ClaudeCLIAdapter` every real
stage already uses (not a parallel LLM-calling mechanism) — a purpose-built
prompt, not a `Stage` enum member (a formal pipeline stage implies graph
routing via `main_graph.json` edges, which doesn't fit an internally-
triggered, off-pipeline review). The response must be a fenced evidence
block (reusing `extract_evidence_blocks`, the same primitive every gate
already uses) containing an array of proposed adjustments, each with:
`gate_id`, `stage` (if a membership change), `change` (`{param, from, to}`
or `{action: "add"|"remove", gate_id}`), `rationale`, `confidence`
(`HIGH`/`MEDIUM`/`LOW`), `risk_level` (`LOW`/`HIGH`).

**Mechanical enforcement**: the response is validated by a new gate script,
`tools/verification_flow/self_tuning_proposal_gate.py`, invoked through the
existing `run_gate()` primitive (not a new stage-gate registration) —
checks the evidence shape, and **rejects (strips) any proposal touching a
protected gate_id/stage** regardless of the LLM's own reasoning. This is
the real backstop — the protected list is enforced in code here, not
merely described in the prompt.

### 4. Apply / defer-to-human, and audit

For each surviving (non-rejected) proposal:
- **Auto-apply** (writes to the two JSON files immediately) when: `confidence
  == HIGH`, the change is a parameter adjustment (not a membership
  `remove`), the gate is not on the "elevated scrutiny" middle tier (see
  Safety boundary), this review cycle proposes only this one change for
  this gate, and this gate/param wasn't reverted within the last 3 review
  cycles.
- **Defer** (write a `PENDING` record, do not touch the JSON files) when
  any of: `confidence != HIGH`, `risk_level == HIGH`, the change is a
  membership `remove`, the gate is in the elevated-scrutiny tier, multiple
  gates are being changed in the same cycle, or this gate/param was
  reverted recently. A deferred record is applied only via
  `dv-harness self-tune approve <id>`.

Every outcome (auto-applied or deferred, and later approved/rejected/
reverted) is persisted as an Engineering Memory record, `kind=
"self_tuning_adjustment"`, `scope="engine"`, with the full evidence,
rationale, and before/after values — **not** pushed to the shared
cross-user Knowledge Center (project-specific tuning state should not leak
into another project's baseline).

New CLI subcommands (`dv_harness/cli.py`, following existing patterns):
```
dv-harness self-tune status                  # counter, pending count, last review time
dv-harness self-tune list [--pending|--applied]
dv-harness self-tune approve <adjustment_id>
dv-harness self-tune reject <adjustment_id>
dv-harness self-tune revert <adjustment_id>  # restores exact prior JSON state
```

---

## Safety boundary

**Architectural invariant** (see Global Constraints): self-tuning cannot
touch `.py` source, so every safety mechanism that lives in Python control
flow (the `PROMOTION_READINESS`/`SIGNOFF`/high-risk-`RE_AUDIT` `WAIT_USER`
hard-stop in `engine.py`, the credential-inspection deny patterns in
`remote_relay.py`, RTL write-scope enforcement's actual denial logic) is
already outside the reachable surface, full stop.

**Removal-protected gate_ids** (`self_tuning_proposal_gate.py`'s hardcoded
denylist — a `remove` proposal naming any of these, for their listed
stage, is stripped before any apply/defer decision):
- `rtl_write_scope_guard_gate` — `IMPLEMENT`
- `fix_risk_approval_gate` — `RE_AUDIT`
- `manual_lookup_before_edit_gate`, `protocol_isolation_gate` — `IMPLEMENT`
- every gate_id listed under `STAGE_GATES["PROMOTION_READINESS"]` and
  `STAGE_GATES["SIGNOFF"]` (whole-stage protection, not enumerated
  individually since that list can grow)

**Parameter-exposure-protected gate_ids** (even once refactored for
`get_param()`, these specific pass/fail-determining thresholds stay
hardcoded, never exposed — a narrower carve-out than the whole gate being
off-limits, for gates that have both tunable-safe and never-tunable
values):
- `fix_risk_approval_gate.py` — the risk/DUT_BUG classification threshold
- `deep_rca_evidence_gate.py`, `root_cause_evidence_gate.py` — minimum
  evidence completeness requirements (hypothesis count, whether hash/ref
  verification is mandatory)
- `regression_submission_policy_gate.py` — the FSDB/PA/COVERAGE default-off
  policy and the `prior_failure_ref`-must-resolve-to-a-real-failure
  requirement

**Elevated-scrutiny tier** (not protected from tuning outright, but any
proposal touching these always defers to human approval rather than
auto-applying): gates enforcing evidence completeness/freshness broadly
(`deep_rca_evidence_gate`, `root_cause_evidence_gate`,
`focused_wave_debug_window_gate`) and anything in `RE_AUDIT`'s or
`FAILURE_RECOVERY`'s gate list not already fully protected above.

**Open item, deliberately not resolved by this spec**: whether this list is
complete. The implementation plan's first task should include a real audit
(grepping the current gate catalog for safety/approval/write-scope-shaped
logic) rather than trusting this hand-assembled list as final — this spec
provides the *mechanism and category definitions*, not a certified-complete
enumeration.

---

## Data flow summary

```
run_stage() reaches terminal verdict
  → gate_history.jsonl append (every gate invocation this run touched)
  → executions_since_last_review += 1
  → if >= N:
      assemble evidence (gate_history since last review, correction
      records, current parameters/overrides, adjustment history)
      → dispatch to ClaudeCLIAdapter with the review prompt
      → extract_evidence_blocks() the response
      → run_gate() against self_tuning_proposal_gate.py
          (strips protected-list violations)
      → for each surviving proposal:
          classify auto-apply vs defer (per the rules above)
          → auto-apply: write parameters.json/stage_gate_overrides.json,
            record kind="self_tuning_adjustment" (status=APPLIED)
          → defer: record kind="self_tuning_adjustment" (status=PENDING),
            no JSON write
      → reset executions_since_last_review = 0
```

## Error handling

- Adapter failure during the review (same failure modes as any stage
  dispatch): the review is skipped, counter is **not** reset (so it
  retries at the next real `run_stage()` call, not stuck forever) —
  logged, never raised up to break the calling `run_stage()`'s own result.
- `self_tuning_proposal_gate.py` failing outright (malformed evidence):
  no adjustments applied or deferred this cycle; counter still resets
  (malformed output isn't worth re-analyzing the same evidence again
  immediately — next cycle's fresh N executions will include this failure
  as new signal).
- Any exception anywhere in the review path is caught at the top level of
  the inline call site, matching the existing defensive pattern used by
  `memory_router._maybe_share`/`maybe_push_to_shared` — a self-tuning
  failure must never break or block the real stage result it's piggy-
  backing on.

## Testing strategy

- `dv_harness/self_tuning.py`'s `get_param()`: unit tests for present/
  absent/malformed parameter file.
- `effective_stage_gates()`: unit tests proving overlay add/remove works,
  and proving a `remove` naming a protected gate_id is silently ignored
  (the core safety-invariant test).
- `self_tuning_proposal_gate.py`: unit tests per protected-list category
  (removal-protected, parameter-exposure-protected) plus normal-case
  pass-through.
- Auto-apply vs. defer classification: unit tests for every rule in
  "Apply / defer-to-human" as an isolated, pure function (not requiring a
  real adapter dispatch).
- End-to-end: a test driving `run_stage()` N times with a mocked adapter
  whose final call returns a canned proposal, asserting the JSON files are
  written (auto-apply case) or a PENDING record exists with no JSON writes
  (defer case), following the same fake-adapter-response test pattern
  already used across `test_engine_gates_and_routing.py`.
- `dv-harness self-tune revert`: test that it restores byte-identical
  prior JSON content, including for a chain of multiple adjustments to the
  same gate (revert only the targeted one, not everything since).

## Rollout plan (not all 60+ gates in one pass)

1. Build the mechanism (components 1-4) with **zero** gates refactored yet
   — provable via tests using synthetic gate_ids, no real gate script
   changes required to validate the engine works.
2. Real safety-list audit (the "open item" above) as its own task, before
   any real gate is touched.
3. Refactor an initial batch of already-well-understood, already-tested
   gates (candidates: `focused_wave_debug_window_gate`'s numeric window
   margin, `DEFAULT_LISTEN_BACKLOG`-style non-gate-script constants are
   explicitly NOT in scope — this is gate *verification logic* only, not
   relay/transport tuning) to expose `get_param()`, each with its own
   before/after regression test proving the default value is unchanged
   when no override is present (pure refactor, no behavior change without
   an actual override file).
4. Remaining gates follow in later, separately-scoped batches — not part
   of this spec's initial implementation plan.

## Non-goals

- No model weights, gradient updates, or neural-network-style learning.
- No autonomous modification of prompt/instruction *text*
  (`STAGE_INSTRUCTIONS`) — this spec is scoped to gate *parameters and
  membership* only, per the three categories the user explicitly selected.
  Prompt-text auto-patching (raised as a lower-risk alternative earlier in
  design discussion) is a separate, future spec if wanted.
- No cross-project sharing of tuning state — this is local to one
  `--project-root`'s own `.dv-harness/`, consistent with
  `USAGE_MULTI_USER_SAFETY.md`'s "never share a `--project-root`" rule.
- No touching of `remote_relay.py`/`remote_exec.py` transport-layer
  constants (backlog size, idle timeout, etc.) — out of scope; this spec
  is about DV *verification* gates only.
