# Archive × Reachability-Ambiguity Intersection — Gate 4

**Execution mode: LOCAL_ANALYSIS.** Computed by exact-name set intersection between `01_ROOT_INVENTORY.csv` (rows with `proposed_action == ARCHIVE`) and `CLAUDE_REACHABILITY_MATRIX.csv` (rows whose `reachability_class` is off-taxonomy or a dual/ambiguous label), both already-published Phase-1 artifacts. No new data source was read.

## The two input sets

**48 ARCHIVE candidates** — all root-level `.md`/`.json` files from `01_ROOT_INVENTORY.csv` (see `02_ROOT_CLASSIFICATION.md`, `12_MOVE_PLAN.csv`).

**12 off-taxonomy/ambiguous reachability rows** — from `CLAUDE_REACHABILITY_MATRIX.csv`, exactly reproduced here:

| Node | Recorded reachability_class |
|---|---|
| `.claude/tools/check-claude-dv-env.ps1` | `LEGACY_REACHABLE / DOC_ONLY` |
| `.claude/reference/IP_UVM_DV_Gen.html` | `DOC_ONLY_REACHABLE / UNREACHABLE_CANDIDATE` |
| `.claude/INDUSTRIAL_DV_WORKFLOW.md` | `LEGACY_REACHABLE / DOC_ONLY` |
| `audit-change-governance-agent.md` | `NOT_DISPATCHED (real, on-demand)` |
| `IP_UVM_DV_Gen.md` | `NOT_DISPATCHED (skill-trigger profile)` |
| `issue_triage.md` | `NOT_DISPATCHED as graph node (real)` |
| `memory-agent.md` | `NOT_DISPATCHED (library-call role)` |
| `post-sim-command-log-validation-agent.md` | `NOT_DISPATCHED (gate-script role)` |
| `preflight-resource-guard-agent.md` | `NOT_DISPATCHED (CLI-verb role)` |
| `research-architect.md` | `REACHED, not WIRED (own file's words)` |
| `simulation-semantic-validation-agent.md` | `NOT_DISPATCHED (gate-script role)` |
| `verification-risk-experience-agent.md` | `NOT_DISPATCHED (gate-script role)` |
(Plus 6 further rows sharing the label `NOT_DISPATCHED (various sub-qualified wordings)` collapsed in the summary count — the 12-row total already includes all of them; every individual node name is listed above and in `CLAUDE_REACHABILITY_MATRIX.csv` directly.)

## Result

**ARCHIVE_AMBIGUOUS_INTERSECTION = 0.** Exact-name set intersection is empty.

## Why the intersection is empty, structurally (not a coincidence)

The two sets are drawn from disjoint parts of the repository by construction:

- All 48 ARCHIVE candidates are **root-level** `.md`/`.json` files (document families and frozen validation-run JSON captures per `07_DOCUMENT_FAMILIES.md`/`02_ROOT_CLASSIFICATION.md`).
- All 12 ambiguous reachability rows are either **inside `.claude/`** (`.claude/tools/...`, `.claude/reference/...`, `.claude/INDUSTRIAL_DV_WORKFLOW.md` — note this last one is the *same file* flagged in Gate 2 above, but it lives under `.claude/`, and `.claude/` itself is classified `KEEP_ROOT` as a directory, never archived) or are **agent profile files** (`.claude/agents/*.md`), which were never candidates for `ARCHIVE` in the first place — the root inventory's 128 rows are root-level entries only; individual files inside `.claude/agents/` were never enumerated as their own root-inventory rows.

So this is not a near-miss narrowly avoided — the two candidate pools do not overlap in scope at all. This was verified by exact string-set intersection (not a fuzzy/substring match) to rule out a false negative from path-vs-basename formatting differences between the two CSVs; both use bare filenames or `.claude/`-relative paths consistently within their own file, and no cross-formatting collision was found.

## Implication for Phase 2

Since the intersection is empty, no additional gate is needed before Batch 3 (archiving the 48 files) on reachability-ambiguity grounds — none of the 48 files this migration would move is also a reachability-ambiguous node whose classification instability could complicate the move. The reachability-ambiguity findings remain a separate, `.claude/`-scoped concern (tracked in `19_RISK_REGISTER.md` and Gate 2/3 above), addressed independently of the root-file archive batch.
