# Stage 1 — Research Intent Routing + `/research` Front Door

**Status: DONE.**
**Scope: Stage 0 audit findings → Stage 1 install only.** No real paper or standard
was ingested or analyzed (Stage 2 boundary). No capability-evolution change was
implemented (Stage 3 boundary). Nothing was promoted to Organizational Memory.
**Mode: LOCAL_ANALYSIS** — no server, no VCS, no simulation.

Master prompt sections in scope: **17** (Research Intent Routing), **18** (Future
Daily Research Invocation), **19 / 53** (`/research` command interface and its
semantics), and **Stage-1 acceptance test F** (Future Short Invocation).

---

## 1. What was built

### 1.1 Research intent recognition — an EXTENSION of `dv_harness/router.py`

`dv_harness/router.py` is the module that already owns this repo's dispatch table
(`DEFAULT_ROUTES`) and its resolver (`RouteResolver`), and it is genuinely on the
real path — `engine.py`'s `run_stage()` calls `RouteResolver.resolve()` before
every LLM call. The research classifier was added **into that module**, sharing
that table, rather than as a new module beside it:

| Added | What it is |
|---|---|
| `DEFAULT_ROUTES['research-route'] = 'research-architect'` | One pair added to the existing 7-entry dispatch table. Not decorative: `research_route_plan()` resolves the architect's name **through** this table rather than hardcoding it, which is what keeps one dispatch table in the module instead of two. |
| `resolve_research_intent(evidence)` | Free-text → one of section 17's five intents, or a structured "not a research request". |
| `research_route_plan(decision, root, focus, documents)` | Section 17's default routing as an ordered list of **real installed assets**, each with a real `exists` check against the tree. |
| `RouteResolver.resolve_intent(evidence, focus, documents)` | The runtime front door on the existing resolver object. |

The five intents are section 17's own list verbatim: `RESEARCH_ANALYSIS`,
`RESEARCH_COMPARE`, `RESEARCH_ARCHITECTURE_IMPACT`, `RESEARCH_DEEP_ANALYSIS`,
`RESEARCH_MULTI_DOCUMENT`.

The route is section 17's own default, and every step names the real thing that
performs it:

```
research-ingestion            -> .claude/skills/research-ingestion/SKILL.md
prior-evidence-lookup (if applicable) -> research/evidence_cards/ + MemoryStore.find
research-architect            -> .claude/agents/research-architect.md
human-approval-gate           -> ControlPlane.approve(stage=RESEARCH_CAPABILITY_EVOLUTION)
```

`prior-evidence-lookup` is genuinely conditional, because section 17 says "if
applicable": it is included for `RESEARCH_COMPARE` / `RESEARCH_DEEP_ANALYSIS` /
`RESEARCH_MULTI_DOCUMENT`, or whenever more than one document is supplied, and
skipped (into `skipped_steps`, never silently dropped) for a plain single-document
analysis.

**Contract deliberately mirrors `protocol_router.resolve_protocol()`** — same
`evidence` dict in, never raises, structured `{"resolved": False, …}` for "not
recognized", and a mandatory non-empty `evidence` string on every return
explaining what actually matched. A caller can hold both decisions side by side
because they are the same shape.

**Vocabulary is transcribed, not invented.** The action/subject phrase lists come
from section 17's seven qualifying-example requests and section 6's own source
list (papers, standards, Accellera documents, vendor technical reports and
application notes, architecture reports, engineering articles, benchmark reports,
internal engineering and verification reports). A request qualifies only when
**both** an action and a subject are present; ambiguity resolves to *not*
research, because a missed research request costs one explicit invocation while a
false positive is the interference section 17 forbids.

### 1.2 Non-interference — structural, then tested

Section 17's non-negotiable: "Do not interfere with existing DV/USB/PCIe/Ethernet/
AMBA/MIPI/CAN-FD/regression/failure-triage/coverage/signoff workflows."

**Non-interference here is structural, not a matter of the classifier being
careful.** Nothing on the existing routing path calls any of the new code:
`run_stage()` calls `resolve_protocol()` then `RouteResolver.resolve()`, and
neither is touched — `resolve()`'s signature and its answers are unchanged, and a
test pins the signature as exactly `(self, node, protocol_decision)` so a future
edit cannot quietly add a research parameter to it. A false positive in the
vocabulary can therefore misroute the *new front door*; it cannot reach, delay or
alter a DV stage's route/agent/skills.

Two further deliberate narrowings:

- **The classifier reads two evidence fields, not five.** `protocol_router.py`'s
  `FIELD_ORDER` has five; this reads only `research_intent` (set explicitly by
  the front door) and `protocol_hint` (which `engine._protocol_router_evidence()`
  populates with the live `user_goal` verbatim). `failing_test_name`,
  `active_config`, `modified_files` and `subsystem_boundary` are **excluded on
  purpose**: a git-modified file named `paper.pdf`, or a subsystem boundary
  containing the word "standard", is not a research request, and reading them is
  precisely how a DV debug run would get hijacked. Four such hijack attempts are
  a real test.
- **Adding the route does not promote the agent.** No node in
  `.dv-harness/graph/main_graph.json` declares `research-route`, and
  `agent_dispatch.py` derives dispatch status from the graph (never from
  `DEFAULT_ROUTES`), so `research-architect` stays `NOT_DISPATCHED` exactly as
  `.claude/agents/ROSTER.md` records it. A test asserts this against the real
  shipped graph.

The negative corpus is **21 evidence strings copied out of
`dv_harness_tests/test_protocol_router.py` itself**, not paraphrases — USB3 link
training, PCIe LTSSM, "please continue the regression", "AMAB4 fabric review",
"AXI Stream FIFO underflow", and so on. Each is asserted (a) to classify as
not-research and (b) to make `resolve_protocol()` return a bit-for-bit identical
answer with and without the research classifier having run over the same text.

### 1.3 `/research` front door — section 19's fallback, honestly applied

**`.claude/commands/` does not exist in this repository and never has** (verified:
`find . -type d -name commands` returns nothing; nothing here has ever used Claude
Code's slash-command convention). Section 19's own fallback therefore applies
verbatim: *"If project command conventions differ, implement equivalent behavior
using the repository's native mechanism rather than forcing this exact syntax."*

This repo's native, tested front-door mechanism is the `dv-harness <verb>` CLI
(80+ real subcommands, its own test suites). The entry point was added there:

```
dv-harness research <doc> [<doc> …] [--compare|--impact|--deep]
                          [--focus regression|pss|debug|planning]
                          [--request "<natural language>"]
```

Section 53's semantics are preserved exactly: default = standard one-paper
analysis; `--compare` = stronger prior-evidence comparison; `--impact` =
architecture-impact emphasis; `--deep` = extended evidence + contradiction +
benchmark; `--focus <domain>` = narrowed emphasis with the route unchanged; more
than one document = `RESEARCH_MULTI_DOCUMENT`. Conflicting mode flags and unknown
focus values are refused rather than silently resolved.

**Section 19's "Do NOT place core logic in the command itself" is held
literally.** `commands.cmd_research()` builds an evidence dict and hands it to
`router.resolve_research_intent()` / `research_route_plan()`. A test reads its own
source and fails if it ever contains `open(`, `read_text`,
`build_research_evidence_card`, `decide_recommendation`, `persist_candidate`,
`ControlPlane` or `approve(`. Another test asserts a `--compare` invocation and an
equivalent natural-language request produce the identical step list — section 53's
"must not fork a second implementation".

**Honest limit, stated rather than implied away:** a CLI process cannot invoke a
Claude Skill or Agent. The deliverable of a front door in this harness is the
resolved intent plus the ordered plan (with real asset paths and real existence
checks) that an agent or human then follows. The command does not claim to have
run the pipeline, and its output ends with an explicit STOP line naming the Human
Approval Gate.

---

## 2. Real defect found and fixed in the prior Stage-1 commit

While wiring the route's final step I ran the approval command that
`dv_harness/capability_evolution.py` publishes to humans. **It does not work**, and
had evidently never been executed before being published:

```
$ dv-harness approve --stage RESEARCH_CAPABILITY_EVOLUTION --note x
dv-harness: error: unrecognized arguments: --stage
```

Two independent faults, both in commit `ad518e5`'s
`human_approval_status()["approve_command"]` (also quoted in
`assert_human_approval()`'s error message):

1. **Wrong argument form.** `stage` is a *positional* argument on `dv-harness
   approve`, not `--stage`.
2. **The stage key was excluded by the parser.** `cli.py` had
   `choices=[s.value for s in Stage]`, and `commands._check_stage()` validated
   against the same set, so `RESEARCH_CAPABILITY_EVOLUTION` was rejected by
   argparse *before* `ControlPlane.approve()` — which happily accepts any string,
   and which is the entire reason the prior pass could reuse the Human Approval
   Gate without a new graph node — was ever reached.

Net effect: the Human Approval Gate at the end of the research route was not
operable by the human it instructs. Since my route's last step *is* that gate,
fixing it is in scope rather than deferrable.

**Fix, minimal and without a second mechanism:**

- `commands.APPROVAL_ONLY_STAGES` — real, code-owned approval keys that are
  deliberately not graph stages. It **imports** `capability_evolution.
  HUMAN_APPROVAL_STAGE` rather than re-typing it, so the two cannot drift.
- `commands._check_approval_stage()` and `commands.approval_stage_choices()` are
  used by `cmd_approve` and by `cli.py`'s parser respectively — one source, so
  parser and validation cannot disagree.
- **Scoped to the `approve` verb alone.** `set-stage` / `redirect` / `correct` /
  `cosign` still accept graph stages only, because those drive the real engine
  loop and a non-graph value there would be a broken state, not an approval. A
  test asserts `set-stage RESEARCH_CAPABILITY_EVOLUTION` still fails and that
  every real graph stage remains approvable.
- `approve_command` corrected to the form that actually runs, and a test executes
  the published string as a real subprocess — so it cannot go stale silently
  again.

No production verification-oracle semantics, signoff authority, or git/PR
governance was touched.

---

## 3. REUSE before EXTEND before ADD — what was checked and not built

| Not built | Because this already exists and was used |
|---|---|
| A second router / intent classifier | Extended `dv_harness/router.py`'s own `DEFAULT_ROUTES` + `RouteResolver`. `resolve()` itself is unchanged. |
| A parallel free-text classifier beside `protocol_router` | Same evidence-dict contract, same never-raises rule, same structured-unresolved shape; the two decisions coexist by design. |
| A new graph node / stage for research | None needed. `ControlPlane`'s `stage` key is an arbitrary string, so the Human Approval Gate is the existing `ControlPlane.approve()` keyed on `capability_evolution.HUMAN_APPROVAL_STAGE`. |
| A parallel approval mechanism | The `approve` verb was made reachable for one code-owned key, not given a sibling. |
| A `dv-harness research approve` verb | Would have been a second approval path. Refused. |
| A new prior-evidence store | `research/evidence_cards/` + `memory.MemoryStore.find()` (added by the prior pass) are named by the plan step. |
| Business logic in the command | Enforced by a test that greps `cmd_research`'s own source. |
| `.claude/commands/research.md` | The convention does not exist in this repo; inventing it would have produced an untestable front door. Section 19's fallback used instead. |

---

## 4. Tests

New: `dv_harness_tests/test_research_intent_routing.py` — **84 tests, all
passing.** Coverage:

- **Acceptance test F**: section 18's canonical natural-language string, verbatim
  and asserted to name no agent and no skill, routes `research-ingestion →
  research-architect → human-approval-gate`; every routed step's asset is
  asserted to exist on disk; the same through a real `dv-harness research
  sample_paper.pdf` subprocess and through `--request "<canonical form>"`.
- All seven of section 17's qualifying examples are recognized; five structurally
  different requests select five different intents.
- Conditional prior-evidence lookup, both directions.
- **Non-interference**: 21 real strings from `test_protocol_router.py` classify as
  not-research and leave `resolve_protocol()` bit-for-bit identical;
  `RouteResolver.resolve()`'s signature and answers pinned; four evidence-field
  hijack attempts refused; the seven pre-existing routes unchanged; no graph node
  declares the research route.
- Section 53's flags, focus domains, refusals, one-implementation property, real
  audit event.
- The published approve command executed as a real subprocess; approval-only
  stages proven not to leak into the engine-driving verbs.

Existing suites re-run green, zero regressions:

| Suite | Result |
|---|---|
| `test_protocol_router` + `test_route_resolver_protocol_fold_in` + `test_skill_resolver` + `test_engine_gates_and_routing` + `test_intake_readiness` + `test_intake_upload` + `test_environment_mode_router` + `test_de_local_sim_env_intake_gate` | **328 passed** |
| `test_capability_evolution_research_architect` + `test_research_evidence_card` + `test_agent_dispatch_map` + `test_stats_snapshot` + `test_doc_citation_check` (+ the new suite) | **180 passed** |
| `test_dashboard_interactive` + `test_remote_control` + `test_cli_remote_control` + `test_fix_risk_approval_gate` + `test_self_tuning_cli` + `test_inference_engine_wiring` | **110 passed** |
| `test_doc_citation_check` + `test_cli_blackboard` + `test_cli_git_guard` + `test_cli_question_queue` + `test_self_tuning` | **96 passed** |

---

## 5. Files changed

| File | Change |
|---|---|
| `dv_harness/router.py` | `research-route` added to `DEFAULT_ROUTES`; `resolve_research_intent()`, `research_route_plan()`, `RouteResolver.resolve_intent()`, and the transcribed vocabulary. `resolve()` untouched. |
| `dv_harness/commands.py` | `cmd_research()` (the front door's whole implementation); `APPROVAL_ONLY_STAGES` / `approval_stage_choices()` / `_check_approval_stage()`; `cmd_approve` switched to the approval-scoped check. |
| `dv_harness/cli.py` | `research` subcommand (parser + formatting-only dispatch); `approve`'s `choices` sourced from `commands.approval_stage_choices()`. |
| `dv_harness/capability_evolution.py` | `approve_command` corrected to the form that actually runs, with the defect documented at the site. |
| `.claude/skills/research-ingestion/SKILL.md` | "How this skill is reached" — the prior "an agent following this skill is the only caller" statement was stale for routing. Still explicitly NOT WIRED. |
| `.claude/agents/research-architect.md` | Same, for step 3 of the route. |
| `dv_harness_tests/test_research_intent_routing.py` | New, 84 tests. |
| `industrial/` + `PACKAGE/` `.claude/skills/research-ingestion/SKILL.md` | Deliverable-tree sync per CLAUDE.md's Methodology Consolidation Rule (agents are outside that rule's stated scope and were left as the prior pass had them). |

Concurrency discipline: `git status`/`diff` was checked on every shared file
before and after editing. `dv_harness/stage_progress_display.py` appeared
untracked mid-pass from a concurrent workflow and was deliberately **not** staged.

---

## 6. Boundaries held

- **No Stage 2.** No document read, no evidence card produced, no paper or
  standard analyzed. `research/evidence_cards/` is still empty.
- **No Stage 3.** Nothing implemented on any capability-evolution candidate. The
  route's last step is a stop, and `stops_before_implementation` is a real field
  a test asserts.
- **No memory promotion.** This pass writes nothing to Engineering or
  Organizational Memory.
- **No governance change.** Verification-oracle semantics, signoff authority and
  the gh/git PR-only protection are untouched.

## 7. Known limits, disclosed

1. **The classifier is a vocabulary matcher, not a language model.** It requires
   an action *and* a subject from transcribed lists. A research request phrased
   entirely outside that vocabulary will be missed — the cost is one explicit
   `dv-harness research` invocation, which is the direction the ambiguity was
   deliberately resolved in.
2. **A false positive cannot reach DV routing, but it can misroute the front
   door.** That is the bounded blast radius the structural separation buys; it is
   not zero.
3. **The front door routes; it does not execute.** No CLI process in this harness
   can invoke a Claude Skill or Agent. Making the route *fire* automatically would
   need a graph node, which Stage 1 deliberately does not add.
4. **`CLAUDE.md` was not edited.** The Stage 0 audit recommends extending its
   Methodology Consolidation Rule rather than adding a freestanding
   capability-evolution section; `CLAUDE.md` is also a file concurrent workflows
   in this session are likely touching. Left for the pass that owns that item.
