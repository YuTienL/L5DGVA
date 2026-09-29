# M8 Experience Loop Trace (CAP-M8-EXPLOOP-001)

Preflight evidence only -- FIND, not FIX. No production code touched.

## Conceptual chain required

```
experience generation -> EXPERIENCE_READY -> experience consumer ->
project learning -> knowledge update -> future-task consumption ->
measurable reuse/evolution
```

## Real, independently traced current state

**Two parallel, semantically-related, never-connected mechanisms exist.**
This is the precise root cause -- not "nothing happens," but "two real
things happen, under two different names, with no code path joining
them."

### Mechanism 1 (REAL, WIRED): `engine.py`'s KC-harvest-at-phase-closure

`dv_harness/engine.py` has multiple real call sites
(lines 1944, 3189, 3258, 3434, 3656 -- re-verified this task, not cited
from memory) that:
1. Build a real memory `record` dict (kind, protocol, root_cause,
   confirmation-tracking fields).
2. Call `route_and_store(self.root, record, cfg=self.cfg)` (`memory_
   router.route_and_store`, imported `engine.py:14`) -- a REAL production
   call, exception-wrapped (`except Exception: promotion = {"destination":
   "PROMOTION_FAILED", ...}`, `engine.py:1943-1945`).
3. Emit a REAL event: `self.store.event({..., "event":
   "EXPERIENCE_KNOWLEDGE_PROMOTED", "record_kind": kind, "promotion":
   promotion})` (`engine.py:1947-1949`).

This mechanism is REAL: it writes to the real 5-tier Memory system via
`route_and_store()`, and records a REAL event, `EXPERIENCE_KNOWLEDGE_
PROMOTED` -- a genuinely different string from `EXPERIENCE_READY`.

### Mechanism 2 (SELF-ATTESTED, NEVER CROSS-VERIFIED): `promotion_chain_audit_gate`'s `EXPERIENCE_READY` stage

`dv_harness/gates.py:413` registers `promotion_chain_audit_gate` as one
of 8 gates in the `PROMOTION_READINESS` stage, invoked with an
`EvidenceFlag`-sourced `--audit <tmp.json>` argument.

`EvidenceFlag`'s own docstring (`gates.py:64-73`, quoted verbatim):
**"A CLI flag whose value is agent-attested."** The JSON body comes from
a ` ```dv-harness-evidence:promotion_chain_audit_gate ``` ` fenced block
the responding AGENT itself writes into its own reply text -- the exact
template is shown to the agent in `prompts.py`'s `STAGE_INSTRUCTIONS[
Stage.PROMOTION_READINESS]` (`prompts.py:2611-2624`), which includes a
literal example `{"stage": "EXPERIENCE_READY", "evidence": "..."}` entry
in the `events` list the agent is told to fill in and return.

`tools/verification_flow/promotion_chain_audit_gate.py` (the real script
`gates.py` invokes) reads that self-reported JSON and checks ONLY:
- every mandatory stage name is present (`EXPERIENCE_READY` is mandatory
  in `ORDER[:8] + ["EXPERT_REVIEW_READY","EXPERIENCE_READY","PROMOTABLE"]`,
  lines 16, 49, even on the non-failure path);
- stages appear in monotonic order;
- each present stage carries a non-empty `"evidence"` string (any
  non-empty string -- never independently verified against a real
  artifact).

**There is no code path anywhere that checks whether the agent's claimed
`EXPERIENCE_READY` entry corresponds to a real `EXPERIENCE_KNOWLEDGE_
PROMOTED` event, a real `route_and_store()` call, or any other real
persisted fact for the same task.** The gate structurally validates a
self-attested claim; it never cross-references Mechanism 1's own real
output.

## Six required determinations (dispatch section 3)

| Question | Answer | Evidence |
|---|---|---|
| Where is `EXPERIENCE_READY` produced? | Nowhere in real code -- it is written by the responding AGENT into its own reply text, per the `prompts.py` template | `prompts.py:2611-2624`; `gates.py:64-73` (`EvidenceFlag` docstring) |
| Where is it persisted? | As a self-attested JSON fragment inside the `promotion_chain_audit_gate`'s own temp-file evidence payload -- not as a durable knowledge record | `gates.py`'s generic evidence-extraction mechanism (`EvidenceFlag(kind="file")`) |
| Who consumes it? | `promotion_chain_audit_gate.py`'s own structural presence/order/non-empty-string check, nothing else | `tools/verification_flow/promotion_chain_audit_gate.py:20-51` |
| Does a real production caller exist for the CLAIM's own truth? | NO -- no code re-derives or verifies the claim against Mechanism 1's real output | Confirmed by grep: zero real `_emit`/`store.event`-style call anywhere literally produces `"EXPERIENCE_READY"` as a computed fact |
| Does the result change durable project knowledge? | Mechanism 1 does (real `route_and_store()` calls, real Memory-tier writes) -- but Mechanism 2 (the gate) never observes or requires Mechanism 1 to have actually run for the same task | `engine.py:1944,3189,3258,3434,3656` |
| Does later-task consumption close the loop? | Not established by this trace alone -- see `M8_KNOWLEDGE_CONSUMPTION_AUDIT.md` for the retrieval-side evidence | Cross-referenced, not re-derived here |

## Verdict

`CAP-M8-EXPLOOP-001` status: **CONFIRMED BROKEN, independently re-
reproduced this task** (not merely re-cited from the Capability Matrix).
Root cause, precisely stated: `promotion_chain_audit_gate`'s
`EXPERIENCE_READY` stage is architecturally a self-attested claim,
structurally validated for presence/order/non-empty-string only, with
**zero cross-verification against the real, separately-wired `EXPERIENCE_
KNOWLEDGE_PROMOTED`/`route_and_store()` mechanism** that already exists
and already works for a different purpose in `engine.py`. This is not "no
producer exists" (a producer DOES exist -- Mechanism 1) and not "no
consumer exists" (a consumer DOES exist -- the gate) -- it is a genuine
MISSING PRODUCTION EDGE joining two real, independently-working halves
under mismatched names, exactly the class of gap this program's own
`CONNECT BEFORE EXPAND` principle exists to catch. `CLOSE THE LOOP`/`NO
CAPABILITY ISLANDS` both apply directly: two islands, one bridge missing.

Per FIND-only Preflight scope: this fix is NOT performed here. It belongs
to M8 Implementation Cohort 1 (see `M8_IMPLEMENTATION_COHORT_PLAN.md`).
