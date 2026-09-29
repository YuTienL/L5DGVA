# Gap-close pass: AI mechanism #4 — Route & Skill Resolver

**Status: NO_ACTION_NEEDED**

No file was modified. No commit was made.

## What I did

Independently re-verified every piece of evidence the audit cited, against the
current working tree (not from the audit's text), then ran the tests myself.

## Re-verification results

### 1. The commits are real

`git log --oneline -- dv_harness/router.py dv_harness/protocol_router.py`:

```
6fe388b research(stage-1): route research intent, add the /research front door
6ee42f8 Route & Skill Resolver: make the protocol decision an input to routing, not telemetry
5603728 Wire real protocol/environment-mode resolvers into engine routing
841c9dc Initial commit: baseline snapshot of DV Agent Harness L5 v50
```

`6ee42f8` — the commit the audit says supersedes the prior session's
"static per-graph-node lookup" finding — exists in real history.

### 2. Concurrency check (task step 4)

`git status`: `dv_harness/router.py` and `dv_harness/protocol_router.py` are
**clean** — untouched by the other concurrent workstreams in this pass.
`dv_harness/engine.py` **is** modified by concurrent work, which shifted the
audit's cited line numbers, so I re-located the call sites by content rather
than trusting the numbers. They are all still present and intact:

| Audit's cited location | Actual current location | Status |
|---|---|---|
| `engine.py:2499-2502` | `engine.py:2561-2564` | present, unchanged in substance |
| `engine.py:784-824` (`_protocol_router_evidence`) | `engine.py:785-824` | present |
| `router.py:62-96` (`RouteResolver.resolve`) | present | clean |
| `protocol_router.py:187-242` (`resolve_protocol`) | present | clean |
| `multi_agent.py:98-112` (`delegate`) | present | uses `ri['skills']` |
| `main_graph.json:39, 99` | present | both declare `protocol-router` |

The production path is intact end to end:

```python
# engine.py:2561-2564
protocol_decision = resolve_protocol(self._protocol_router_evidence(user_goal))
route_info = self.router.resolve(node, protocol_decision=protocol_decision)
route_info["protocol_decision"] = protocol_decision
resolved_skills = self.skills.resolve(route_info["skills"])   # folded list, not node.skills
...
task = self.agents.delegate(node, plan, route_info=route_info)  # line 2594
```

```python
# multi_agent.py MultiAgentOrchestrator.delegate()
skills = ri['skills'] if ri.get('skills') is not None else node.skills
```

The `node.skills` fallback fires only when `route_info` is `None`, and
`run_stage()` always supplies one. No bypass.

### 3. I re-ran the falsification test myself

Loaded the real `.dv-harness/graph/main_graph.json` via the real
`GraphDefinition.load()`, called the real `RouteResolver` with real
`resolve_protocol()` output, on four real nodes:

```
--- DISCOVERY   static ['subsystem-to-soc-verification', 'protocol-router']
   USB  usb  -> [...,'protocol-router','usb-profile','usb-vip-lookup']  added ['USB/usb-profile','USB/usb-vip-lookup']
   PCIe pcie -> [...,'protocol-router','pcie-profile']                  added ['PCIe/pcie-profile']
   NONE None -> [...,'protocol-router']                                 added []
--- PROTOCOL_CAPABILITY  static ['protocol-router']
   USB / PCIe / NONE -> three different skill lists (same pattern)
--- IMPLEMENT   static ['workflow-closure-loop']    -> identical for all three evidence sets
--- GIT_SYNC    static ['git-pull-sync','git-workflow'] -> identical for all three evidence sets
```

This reproduces the audit's claim exactly — **same node, same static table,
three different real outcomes** — and also independently reproduces the audit's
*disclosed scope boundary* (`IMPLEMENT`/`GIT_SYNC` output == static input,
because `_is_protocol_sensitive()` is `False` for them).

### 4. Tests pass

```
dv_harness_tests/test_route_resolver_protocol_fold_in.py
dv_harness_tests/test_protocol_and_environment_mode_engine_wiring.py
dv_harness_tests/test_protocol_router.py
-> 41 passed in 30.59s
```

I read `test_same_node_two_evidence_sets_produce_different_delegated_skills`
rather than trusting its name. It genuinely drives a real `DVHarness.run_stage()`
with a deliberately protocol-free `user_goal` (so the only protocol signal is a
seeded failing test name), then asserts on the **real persisted**
`AgentTaskStore` record, the real ReAct action record, and the real prompt the
adapter received — closing "resolved" vs. "actually delegated". That is an
engine-level proof, not a unit test of the pure function.

## Why no fix

The audit's verdict is WIRED_AND_FIRING and names no gap. Per task rule 1, the
correct action is to change nothing. I found no reason to overturn that verdict:
every cited artifact exists, the traced path has no bypass, and the behavioral
difference is reproducible on demand.

I specifically checked whether the audit's "disclosed scope boundary" was a
concealed gap rather than a design limit. It is a design limit:

- **`route`/`agent` stay static by design.** `router.py`'s own docstring states
  the ruling: `resolve_protocol()`'s `route` is a *skill* route (`USB/usb-profile`),
  not a graph route, and no evidence source in this harness maps a protocol to a
  different agent — "inventing one would be fabrication, not routing."
- **Only 2 of ~20+ nodes are protocol-sensitive.** `RouteResolver.resolve()` does
  execute for every node (verified above: `IMPLEMENT` and `GIT_SYNC` run through
  it and return their static list), so this is opt-in via the node's own
  `protocol-router` skill declaration, not a skipped code path. Appending
  `usb-profile` to `GIT_SYNC` would be noise, not routing.

Both boundaries are stated in the code's own comments and are consistent with
the `question_queue.route_owner()` / `connectivity.py` T1–T4 classify-then-lookup
pattern, so this is a converged codebase pattern rather than a one-off.

## Follow-up (not attempted, not required now)

If a future need arises to make resolution evidence-driven along axes *other
than* protocol, or for stages beyond the two `protocol-router`-declaring nodes,
that needs new fold-in logic analogous to `protocol_skill_routes()`. It does not
exist today and nothing in the code claims it does.
