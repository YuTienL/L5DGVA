# Broken Skill Reference — Gate 3

**Execution mode: LOCAL_ANALYSIS.** No skill was created, renamed, or modified.

## The reference

`.dv-harness/graph/main_graph.json`, node `EXPERT_FEEDBACK_LOOP` (line 420):
```json
"skills": ["expert-feedback-closure"]
```

## The real skill

`.claude/skills/EXPERT_FEEDBACK/dv-expert-feedback-closure/SKILL.md`, frontmatter:
```yaml
name: dv-expert-feedback-closure
description: Patch/regenerate, compile, smoke, regress and return closure evidence for expert re-review.
```

The directory name and the frontmatter `name:` field agree with each other (`dv-expert-feedback-closure`) but **neither matches** the graph's `expert-feedback-closure` (missing the `dv-` prefix).

## Systematic check: is this an isolated case or a pattern?

`main_graph.json` names 47 skill references (`"skills": [...]` across all 37 nodes with a non-empty list). Every one of the other 46 resolves to a real `.claude/skills/**` directory of the same name. `expert-feedback-closure` is the **only** one that does not. This rules out a systematic prefix-drift across the file — it is a single, isolated broken reference.

## Determining which of the four possibilities applies

- **Removed**: ruled out — the skill exists, fully formed, with real content (not a stub).
- **Replaced**: ruled out — no other skill in `EXPERT_FEEDBACK/` or elsewhere claims ownership of the `EXPERT_FEEDBACK_LOOP` node's job; `dv-expert-feedback-closure` is clearly the intended skill by description match (its stated purpose — "Patch/regenerate, compile, smoke, regress and return closure evidence for expert re-review" — is exactly what the `review-agent`-owned `EXPERT_FEEDBACK_LOOP` node needs).
- **Genuinely missing**: ruled out — the correctly-named skill exists and is well-formed.
- **Renamed**: **plausible but not provable.** `v50`'s entire git history is a single squashed commit (`3238329 Initial commit: baseline snapshot of DV Agent Harness L5 v50`) — there is no rename/move history to inspect (`git log --all --follow -- "*expert-feedback-closure*"` and `--diff-filter=R` both return nothing beyond that one commit). It is impossible to determine from this repository's history alone whether `expert-feedback-closure` was ever a real skill name that got renamed to `dv-expert-feedback-closure` with the graph left stale, or whether the graph node was simply mistyped (missing the `dv-` prefix that the other 46 references consistently carry) from the moment this snapshot was taken.

## Verdict

**MISTYPED_REFERENCE, not RENAMED/REMOVED/REPLACED/GENUINELY_MISSING.** The evidence supports one specific, narrow conclusion: `main_graph.json`'s `EXPERT_FEEDBACK_LOOP` node should reference `dv-expert-feedback-closure` (the one real, correctly-formed skill whose description matches the node's job), and currently does not, due to a missing `dv-` prefix. This is the only unresolved skill-name reference among 47 in the file. Whether the *cause* was a historical rename or a day-one typo cannot be determined from available evidence (single squashed commit) and is disclosed as unresolvable rather than guessed.

## Runtime-invocation caveat (still applies)

Per this audit's standing caveat: a skill can still be invoked by Claude Code's own Skill tool via exact name or description match at runtime, independent of what a graph JSON file says. This means `EXPERT_FEEDBACK_LOOP`'s dispatched agent (`review-agent`) could in principle still reach `dv-expert-feedback-closure` by description-match even with the graph reference broken — this review did not verify whether that actually happens in practice (would require a live dispatch trace, out of scope for LOCAL_ANALYSIS), so the broken graph reference should still be treated as a real defect, not assumed harmless.

## Disposition

**No replacement skill was created.** No file was edited (`main_graph.json` is runtime state, not an audit artifact, and is out of this task's allowed-writes scope regardless). This finding is unchanged in substance from the Phase-1 report in `05_AUTHORITY_GRAPH.md`; this review adds the systematic 47-reference check (confirming it is isolated) and the exact verdict/history-limitation analysis above.
