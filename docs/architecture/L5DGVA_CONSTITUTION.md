# L5DGVA Constitution

This document is the canonical, full-text reference for the L5DGVA
Constitution. `CLAUDE.md`'s own opening section carries the same Article 0
and all supporting sections in full (not merely a pointer — both documents
are kept in sync and neither contradicts the other); this file exists as a
stable, non-resident reference and as the target of CLAUDE.md's own
cross-reference, consistent with `docs/architecture/` being this project's
canonical home for architecture-level documents (per the M1D root
normalization).

Enforced in code: `dv_harness/constitution_gate.py`
(`check_constitution_intact()`), with real tests in
`dv_harness_tests/test_l5dgva_constitution.py` that fail if this file, or
CLAUDE.md's own Article 0 section, is silently removed or weakened.

---

## Article 0 — Highest Governing Principle

L5DGVA 是一個 location-independent、evidence-grounded、knowledge-driven、
continuously evolving 的 Multi-Agent DV Platform。

它能針對 IP、Subsystem、System-Level，自動完成從 OpenSpec Intake、DV
Knowledge Retrieval、vPlan、VIP/UVM Verification Environment Generation、
Remote EDA Execution、Regression、RCA、Functional Coverage Closure、
Requirements Traceability 到 Signoff 的完整驗證閉環。

它並同時從外部 DV Research / Papers / New Technologies，以及內部 Project /
User Interaction / Generation / Debug / RCA / Coverage Closure / Signoff
Experience，持續萃取、驗證、晉升與重用工程知識，使下一次 Verification
Generation 更準確、更自動、更高品質。

**Normative English form:**

> L5DGVA is a location-independent, evidence-grounded, knowledge-driven,
> continuously evolving Multi-Agent DV Platform.
>
> Its purpose is to automatically support IP, Subsystem, and System-Level
> verification from OpenSpec Intake through DV Knowledge Retrieval,
> Discovery, vPlan, VIP/UVM Verification Environment Generation, Remote EDA
> Execution, Regression, RCA, Functional Coverage Closure, Requirements
> Traceability, Signoff, and Experience Consolidation.
>
> L5DGVA continuously improves by extracting, validating, promoting, and
> reusing engineering knowledge from:
>
> A. external DV research, papers, methodologies, tools, and new
>    technologies; and
> B. internal project execution, user interaction, clarification,
>    generation decisions, simulation, debug, RCA, regression, coverage
>    closure, and signoff experience.

**All future architecture, migration, implementation, agent, skill,
workflow, graph, governance, testing and product decisions are subordinate
to Article 0. No local optimization may silently weaken Article 0.**

## The Five Constitutional Dimensions

1. **LOCATION_INDEPENDENT** — must support copy/clone/move/rename/
   archive-extract, different users, different repository paths, Windows
   bootstrap, WSL2, Docker-mounted runtime; canonical identity must not
   depend on the absolute bootstrap path, directory basename, a specific
   username, gateway/remote-EDA hostname, or personal Obsidian Vault path.
   Enforced today by `dv_harness/l5dgva_repo.py`,
   `dv_harness/execution_profile.py`, `dv_harness/root_hygiene_gate.py`.
2. **EVIDENCE_GROUNDED** — Hypothesis → Evidence → Confidence → Validation
   → Action; every conclusion is backed by current, re-checkable evidence,
   never memory/prior-summary/self-attestation alone. AI inference alone is
   not sufficient evidence.
3. **KNOWLEDGE_DRIVEN** — generation/debug/coverage decisions consult the
   Knowledge Brain (KC Engine, five-tier Memory, Obsidian) and validated
   external research before deciding, where the workflow supports it.
   Knowledge is not operational merely because it is stored — operational
   knowledge requires retrieval → applicability validation → agent
   consumption → decision/action impact → recorded evidence.
4. **CONTINUOUS_EVOLUTION** — the platform improves over time via two named
   loops (below), not a static generator. A single project observation must
   NOT automatically become a universal engineering rule.
5. **END_TO_END_DV_ALIGNMENT** — measured against the full intake-to-signoff
   chain named in Article 0, not any single stage in isolation.

## The Two Continuous Learning Loops

**EXTERNAL LEARNING LOOP**: DV Paper / New Technology → Research Ingestion
→ Distillation → Claims/Method Extraction → Evidence/Provenance →
Applicability Analysis → L5DGVA Capability Gap → Capability Candidate →
Experiment/Validation → Accept/Reject → Canonical Capability Evolution. A
research summary document alone does NOT qualify this capability as
operational — research must be capable of affecting validated future
L5DGVA capability to qualify as a closed loop.

**INTERNAL LEARNING LOOP**: User Interaction / Project Execution →
Generation / Simulation / RCA / Regression / Coverage / Signoff →
Experience Extraction → Evidence Grounding → Applicability / Generalization
→ Knowledge Promotion → Capability Evolution, covering Intake, User
Interaction, Clarification, DUT/RTL/VIP/Topology Discovery, Generation
Decisions, UVM Architecture, Sequence/Scenario Generation, Firmware/IRQ
Integration, Build/Simulation Failures, Debug, RCA, Fixes, Regression,
Coverage Holes/Closure, Waivers, and Signoff.

**Clarification Learning** (part of the internal loop): question asked →
user answer → later evidence proves the answer was auto-discoverable →
`QUESTION_AVOIDABLE` → improve discovery strategy → reduce unnecessary
future clarification. Does NOT authorize guessing — auto-discovery must
remain evidence-grounded.

**Experience Consolidation**: `SIGNOFF_READY → SIGNOFF →
EXPERIENCE_CONSOLIDATION → COMPLETE`. Incremental learning accumulates in
M2 Job Memory during execution; at project closure, M2 Job → M3 Project;
cross-project validated knowledge, M3 → M4 Engineering;
organization-reusable knowledge, M4 → M5 Organizational → Obsidian.

Together: `CONTINUOUS_CAPABILITY_EVOLUTION`. Real current status (per the
M3 capability-family audit,
`.work/phase3-dual-repo-consolidation/CANONICAL_CAPABILITY_SUPERSET_MATRIX.md`):
the external loop's research→candidate→experiment path is real,
`IMPLEMENTED`/`WIRED`/`TRIGGERED`/`TESTED`. The internal loop's
`EXPERIENCE_READY` promotion-gate wiring is confirmed **broken on every
source tree** (Parent, v50, canonical) — a real, disclosed, pre-existing
gap, not a migration omission, explicitly owned by M8.

## Generic Verification Level Principle

The same generic L5DGVA core serves IP, SUBSYSTEM, and SYSTEM_LEVEL scope —
three independent duplicated orchestration engines must not become the
default architecture. Differences are expressed through evidence-supported
extension mechanisms (level profiles, protocol profiles, topology,
capability adapters, registries, configuration). The final product must
prove all three levels end-to-end.

## Maximum Verified Capability Union

The final Canonical L5DGVA is NOT a v50 copy, and NOT a Parent overwrite —
it is the **Maximum Verified Capability Union** of all approved migration
sources, followed by semantic-conflict resolution, defect correction,
capability operationalization, and new operational capabilities. Maximum
capability union does NOT mean maximum file union: duplicate, obsolete,
generated, inferior, or non-operational duplicate implementations do not
need to survive as duplicate files. No verified source capability may be
silently lost.

## Capability Operationalization Standard

`IMPLEMENTED` / `WIRED` / `TRIGGERED` / `CONSUMED` / `OBSERVED` / `TESTED` —
existence alone never qualifies a claim at a higher level than the real
evidence supports. Telemetry existing is not consumption; tests existing
are not proof of real workflow use. Preserve truthful
PARTIAL/DORMANT/AUDIT_TELEMETRY states; never inflate completion status.

## Knowledge Authority Boundary

OpenSpec/Intake = requirement authority. Git/canonical implementation =
implementation authority. Runtime Evidence = execution truth. KC/Memory/
Obsidian = engineering knowledge/rationale — never a competing
source of truth. A contradiction between knowledge and authoritative
requirement/runtime evidence must trigger evidence resolution/clarification,
never a silent knowledge override.

## Canonical Platform Architecture (governance-level reference)

**ZONE 1 — LOCAL_CONTROL** (WSL2): Claude CLI/Multi-Agent, Git/Worktrees,
OpenSpec/Intake, L5DGVA, Knowledge Brain, Generation, ExecutionService,
LocalBackend, Docker, RemoteEDABackend client. **ZONE 2 — ACCESS_GATEWAY**:
transport only — no decision logic, no source-of-truth role. **ZONE 3 —
REMOTE_EDA**: VCS, LSF, Verdi/FSDB, ZeBu, HAPS, Coverage — an execution
plane, not a source of truth. Host identities belong to execution
profiles/configuration, never hard-coded into generic architecture.

**Execution abstraction target** (not yet implemented): L5 component →
ExecutionService → ExecutionBackend (LocalBackend / RemoteEDABackend);
remote target: RemoteEDABackend → TelnetSSHTransport → existing
`remote_hop`/`remote_relay` → Remote EDA. The existing known-good transport
is wrapped first, never unnecessarily rewritten.

**Knowledge Brain target**: KC Engine + M1 Working + M2 Job + M3 Project +
M4 Engineering + M5 Organizational + KnowledgeService + Obsidian
Adapter/CLI/Vault + Multi-Agent consumers, all through the Knowledge
architecture rather than ad hoc direct Obsidian behavior per agent.

## Anti-Drift Rule

If a future change conflicts with Article 0 or one of the five
constitutional dimensions: identify the conflict, preserve the current
valid baseline, report concrete evidence, emit `ARCHITECTURE_CONFLICT`,
STOP the conflicting change, and require explicit architectural review —
never silently weaken, narrow, or route around the principle. Do not weaken
Article 0 merely to make implementation or tests easier.

## Migration-Wave Scoping (does not expand any current wave's scope)

Article 0 describes the FINAL product. No single wave must satisfy it in
full. Each wave may honestly report `PARTIAL` with a declared future owner
wave (`HIGHEST_PRINCIPLE_COMPLIANCE`: `LOCATION_INDEPENDENT` /
`EVIDENCE_GROUNDED` / `KNOWLEDGE_DRIVEN` / `CONTINUOUS_EVOLUTION` /
`END_TO_END_DV_ALIGNMENT`, each `PASS`/`PARTIAL`/`FAIL` with evidence). In
particular: M3 (independent/leaf capability migration) is explicitly NOT
expanded to implement M8-M13 capabilities merely because Article 0 names
them as the eventual target.

## Milestone Capability Gates

```
M1:   Canonical >= qualified v50 required baseline
M8:   Canonical >= Maximum Verified Capability Union of approved sources
M13:  Canonical >  Maximum Verified Capability Union of approved sources
```

Final strict-superset gate: `SOURCE_CAPABILITY_LOSS = 0`,
`SOURCE_VERIFIED_CAPABILITIES_PRESERVED = 100%`,
`CANONICAL_NEW_OPERATIONAL_CAPABILITIES > 0`,
`CANONICAL_ENHANCED_CAPABILITIES > 0`,
`CANONICAL_CAPABILITY_STRICT_SUPERSET = PASS` — never claimed early.

## Final Constitutional Acceptance

```
L5DGVA_CONSTITUTIONAL_COMPLIANCE = PASS
```

is a mandatory, final-product-only acceptance requirement, additional to
`CANONICAL_CAPABILITY_STRICT_SUPERSET = PASS`. Final completion must
eventually prove at least: `LOCATION_INDEPENDENT = PASS`,
`EVIDENCE_GROUNDED_DECISION_FLOW = PASS`, `KNOWLEDGE_DRIVEN_GENERATION =
PASS`, `CONTINUOUS_RESEARCH_EVOLUTION = OPERATIONAL`,
`CONTINUOUS_PROJECT_EXPERIENCE_LEARNING = OPERATIONAL`,
`IP_END_TO_END = PASS`, `SUBSYSTEM_END_TO_END = PASS`,
`SYSTEM_LEVEL_END_TO_END = PASS`, `VPLAN_TO_COVERAGE_SIGNOFF = PASS`,
`REQUIREMENTS_TRACEABILITY = PASS`, `KNOWLEDGE_PROMOTION = PASS`,
`AGENT_KNOWLEDGE_CONSUMPTION = OBSERVED`,
`CANONICAL_CAPABILITY_STRICT_SUPERSET = PASS`. Neither gate is claimed by
any intermediate wave, including M3.

## USB / PCIe Qualification Principle

USB = first Golden end-to-end qualification; the Reference USB Environment
must not be consumed before its approved qualification wave (M11). PCIe =
the genericity challenge after USB: `ZERO CORE ORCHESTRATION / GENERATION
CHANGE` except approved protocol profiles, adapters, data, and explicit
extension points — proving the core is generic rather than USB-specific.

## Integration Prime Directive Cross-Reference

Article 0 above describes the FINAL product's end-to-end chain — a static
target, not a sequencing instruction. `docs/architecture/
L5DGVA_INTEGRATION_PRIME_DIRECTIVE.md` is the separate, subordinate,
current-integration-phase instruction for HOW progress toward that chain is
sequenced and measured while it is still being connected
(`CONNECT BEFORE EXPAND -> OPERATIONAL BEFORE CLAIMED -> CLOSE THE LOOP ->
NO CAPABILITY ISLANDS`). It restates no constitutional dimension and adds
no new one — its own `OPERATIONAL BEFORE CLAIMED` maturity ladder
(`ROADMAP_DEFINED -> FOUNDATION -> IMPLEMENTED -> WIRED -> TRIGGERED ->
CONSUMED -> OPERATIONAL -> QUALIFIED`) is a finer-grained restatement of
this document's own **Capability Operationalization Standard** above
(`IMPLEMENTED`/`WIRED`/`TRIGGERED`/`CONSUMED`/`OBSERVED`/`TESTED`),
reconciled rather than duplicated. CLAUDE.md carries only a compact
ALWAYS_ON pointer to it (`Integration Prime Directive` section); this
Constitution is not amended by it and does not duplicate its text.
