---
name: corner-case-risk-ranker
description: Prioritize corner cases using architecture, state, concurrency, reset/CDC, error recovery, novelty, ambiguity and history.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# corner-case-risk-ranker

Prioritize corner cases using architecture, state, concurrency, reset/CDC, error recovery, novelty, ambiguity and history.

## Rules
- Evidence first.
- Do not guess missing architecture/spec behavior.
- Preserve Spec→vPlan→Architecture→Test→Observability→Execution traceability.
- Report counter-evidence and unresolved unknowns.

## Ranking Rule (Iron Rule 149 / 230)

鐵則 149：Corner Case 不得暴力窮舉。必須用 architecture/state/concurrency/reset/error/history/coverage risk 做 P0-P3 排序。

鐵則 230：Protocol Corner Cases 必須有 Evidence-backed Matrix。Required corner cases 必須逐項 covered 並帶 evidence，否則不得 signoff。

Every corner case output gets a P0/P1/P2/P3 label derived from the factors above (architecture, state, concurrency, reset/CDC, error/recovery, novelty, ambiguity, history) -- never emit an unranked list.
