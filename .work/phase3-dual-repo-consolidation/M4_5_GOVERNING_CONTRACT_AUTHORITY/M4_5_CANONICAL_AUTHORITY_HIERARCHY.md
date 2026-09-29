# M4.5 — Canonical Authority Hierarchy (frozen, per human decision)

```
LEVEL 0: L5DGVA Constitution / Article 0
         (docs/architecture/L5DGVA_CONSTITUTION.md + CLAUDE.md's own
         compact Article 0 section -- highest authority)

LEVEL 1: CLAUDE.md Core Always-On Governance
         (42 ALWAYS_ON sections, 112,262-113,125 bytes post-M4.6:
         Core Operating Rules, Evidence Truth Rule, Engineering Memory
         Policy, the 21 cross-cutting hard-boundary rules, the
         Governance Document Routing router)

LEVEL 2: Canonical Governing Contracts
         (individual requirements PROMOTED from a source corpus through
         the full clause-level verification pipeline -- Section 5 of
         this closure. NONE exist yet: this wave promoted 0 of 20
         candidates, per the finding below.)

LEVEL 3: Architecture / Workflow / Capability Contracts
         (the 7 docs/architecture/canonical_detailed_governance/*.md
         TASK_SCOPED documents from M4.6, plus dv_harness/ module
         docstrings, plus .claude/skills/*/SKILL.md)

LEVEL 4: Agents / Skills / Graph / Implementation
         (dv_harness/*.py modules, .claude/agents/*.md, graph.py
         definitions -- the executable layer)
```

`Runtime Evidence` (sim.log, waveform, FSDB, register readback, real
test results) remains **execution truth for what actually occurred**,
outside this hierarchy entirely -- no level above can substitute for it
when the question is "did this actually pass."

## The 25-document governing-contract corpus's place in this hierarchy

**Not in the hierarchy at all.** Per the frozen human decision: the
corpus is a **migration-evidence source**, feeding candidate clauses
into a verification pipeline that may promote individual clauses to
**LEVEL 2** -- but the corpus document itself never becomes an
authority level. It remains `SOURCE_EVIDENCE_ONLY` /
`EVIDENCE_ON_DEMAND`, registered in `dv_harness/governance_registry.json`
as `L5DGVA_GOVERNING_CONTRACT_CORPUS` (unchanged since M4.5's earlier
work, re-verified still correct by this closure).
