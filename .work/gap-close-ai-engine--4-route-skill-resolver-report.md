# Gap close: AI mechanism #4 — Route & Skill Resolver

**Status: DONE**

Audit verdict was PARTIALLY_WIRED with a concrete, in-scope wiring gap. The gap is closed.

## The gap, restated from the code (re-verified before touching anything)

`dv_harness/engine.py`'s `run_stage()` had, in this order:

```python
route_info = self.router.resolve(node)                       # static: node.route/agent/skills
resolved_skills = self.skills.resolve(node.skills)           # static list -> paths
route_info["protocol_decision"] = resolve_protocol(self._protocol_router_evidence(user_goal))
...
task = self.agents.delegate(node, plan)                      # read node.* again, not route_info
```

`resolve_protocol()` was real, fired on real per-run evidence, and was persisted — but it ran
*after* the two resolvers it was supposed to inform, and nothing ever read it back. Two runs of
the same graph node with different evidence produced byte-for-byte identical
`route_info["skills"]`, `resolved_skills`, and delegated `task["skills"]`.

Line numbers had shifted from the audit report (concurrent edits to `engine.py` landed the
`_computed_regression_selection()` / `_escalate_unreachable_coverage_holes()` work in the same
window); the call site itself was unchanged.

## What changed

**`dv_harness/router.py`** — `RouteResolver` now takes a `root` and
`resolve(node, protocol_decision=None)`. When the decision resolved AND the node declared itself
protocol-sensitive, the protocol's real skills are appended to the node's static ones. Returns two
new keys alongside the existing three: `static_skills` (the pre-fold list) and
`protocol_skill_routes` (what the decision added).

`PROTOCOL_SENSITIVE_SKILLS = {"protocol-router"}` is the trigger: a graph node that declares the
`protocol-router` skill has, by its own design-time declaration, said "which skills I need depends
on which protocol this run is about" — `CORE/protocol-router/SKILL.md` is exactly the routing table
`resolve_protocol()` executes, and its "Profile/VIP-Lookup Binding" section instructs that stage to
read the resolved protocol's profile/vip-lookup skills. In the current `main_graph.json` that is
DISCOVERY and PROTOCOL_CAPABILITY — the latter being where the real `protocol_profile_binding_gate`
already checks those same skills were consulted. Deliberately not every node: appending
`USB/usb-profile` to GIT_SYNC would be noise, not routing.

`route`/`agent` deliberately stay the static table's answer. `resolve_protocol()`'s `route` is a
*skill* route (`USB/usb-profile`), not a graph route, and no evidence source anywhere in this
harness maps a protocol onto a different agent — inventing one would be fabrication.

**`dv_harness/protocol_router.py`** — added `load_registry_entry(root, protocol)` and
`protocol_skill_routes(root, decision)`. These do in code what SKILL.md's "Profile/VIP-Lookup
Binding" section previously only asked an agent to do by hand: read the real
`.dv-harness/builder/protocol_builder_registry.json` entry and resolve `profile_skill` /
`vip_lookup_skill`. Returns the primary builder route first, then those two when non-null; `[]` for
an unresolved decision; skips null fields rather than inventing names (eMMC/SD/eDP/UCIe genuinely
have `profile_skill: null`, which SKILL.md itself calls out as expected). The registry-key bridging
(`amba`→`amba4-soc`, `mipi_csi2`→`mipi-csi`, `sdio`→`sd`) reuses the same exact-then-substring rule
`gates._protocol_discover_checklist()` already applies to this same registry.

**`dv_harness/engine.py`** — reordered `run_stage()` so `resolve_protocol()` runs FIRST and is
passed into `self.router.resolve(...)`; `self.skills.resolve()` now takes `route_info["skills"]`,
not `node.skills`; `self.agents.delegate(node, plan, route_info=route_info)`; the dry-run task dict
mirrors `route_info` instead of `node.*`. `RouteResolver(self.root)` at construction. The resolved
and static skill lists plus `protocol_skill_routes` are persisted into the existing ReAct record
and the existing dry-run report (no new persistence mechanism). `_build_plan_section()` names the
registry-path-prefixed routes explicitly, because those are the exact strings
`protocol_profile_binding_gate` expects back in `profile_skills_consulted`.

**`dv_harness/multi_agent.py`** — `MultiAgentOrchestrator.delegate(node, plan, route_info=None)`
delegates the resolved agent/route/skills, falling back to the node's own fields when no
`route_info` is supplied.

**`dv_harness/skill_resolver.py`** — NOTICE updated. Still, correctly, a pure name→path lookup:
*which* skills apply is a routing decision that belongs in `router.py`.

**`.claude/skills/CORE/protocol-router/SKILL.md`** — records that the harness now performs the
binding in code before the stage starts, and that the prompt names the routes verbatim; the manual
lookup stays the definition of correctness and the fallback.

Stale comments in all touched files were rewritten rather than left behind (comment-hygiene rule).

## Verification

New engine-level regression test
`test_same_node_two_evidence_sets_produce_different_delegated_skills` is the audit's own proposed
crux case: the SAME DISCOVERY node, a protocol-free `user_goal`, and two different real
`verification_state` blackboard records (`test_usb3_enum` vs `test_pcie_link_train`). It asserts
`static_skills` are identical (the old answer — the before/after proof is inline) while the
delegated `tasks.json` skills, the ReAct record's skills, and the adapter prompt all differ, and
differ in the specific registry-backed way: USB gains `usb-profile` + `usb-vip-lookup`, PCIe gains
`pcie-profile` only. Three sibling tests cover the negative cases (non-protocol-sensitive node
untouched, unresolved decision changes nothing, folded-in skills resolve to real on-disk paths).

**One-line test summary:** 306 passed (`test_engine_gates_and_routing`, `test_react_loop`,
`test_protocol_router`, `test_skill_resolver`, `test_multi_agent_timing`,
`test_protocol_profile_binding_gate`, `test_environment_mode_router`) + 8 passed
(`test_protocol_and_environment_mode_engine_wiring`, incl. 4 new) + 7 passed
(`test_route_resolver_protocol_fold_in`, new) + 26 passed (`test_protocol_router` incl. 6 new) +
44 passed (`test_harness_reliability`, `test_execution_preflight_wiring` — dry-run report shape) —
zero failures.

## Committed

Hand-scoped: `engine.py` is under concurrent edit by other workstreams in this same pass, so only
this task's 10 hunks were staged via a filtered patch (`git apply --cached --recount`); the
concurrent `_computed_regression_selection()` / `_escalate_unreachable_coverage_holes()` /
REGRESSION_SELECT-prompt hunks were left unstaged for their own owner. Local commit on `master`
only — no push, per the PR-only governance policy.
