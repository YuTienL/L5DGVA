# AMBA-7..14 -- fabric-port endpoint tracing: DONE

Commit `35614ce` -- `amba(discovery): AMBA-7..14 fabric-port endpoint tracing on
a real RTL net graph`.

Audit verdict going in: **NEVER_BUILT for all eight requirements**, and the
audit was right about something more important than the missing traversal --
the port-level connectivity graph such a traversal would consume did not exist
anywhere in this repo either. Both layers are built here.

## What changed

### Layer 1 -- `dv_harness/verible_parser.py`: the missing raw data (+202 lines)

The audit's live grep was correct: zero matches for verible's own
instantiation/port-connection grammar tags. verible's `--export_json --printtree`
tree already carries `kInstantiationBase` / `kGateInstance` / `kPortActualList` /
`kActualNamedPort` / `kActualPositionalPort` / `kContinuousAssignmentStatement`
(every tag confirmed by probing this install directly, never read from
documentation); nothing walked them, so not a single port-to-port connectivity
fact was obtainable.

It now extracts, per module:

- every instantiation (`InstanceInfo`: instance name + instantiated module name),
- every port connection (`PortConnectionInfo`: named and positional alike, with
  the connected expression's BASE identifiers -- `bus[IDX]` yields `bus` and not
  `bus`+`IDX`, because the index is its own nested `kReference`; `{a, b}` yields
  both; an explicitly-unconnected `.p()` is kept as a real fact),
- every continuous `assign` (`ContinuousAssignInfo`: lhs/rhs base identifiers).

Instantiations inside generate blocks are collected (AMBA-7 lists generate
blocks among the structures a trace crosses), stopping at a nested module
declaration so its contents are not mis-scoped.

**One real bug found while testing this**, worth calling out because it would
have silently produced wrong connectivity: verible ELIDES an omitted positional
slot -- `leaf u (a, , c)` -- from the tree entirely, leaving only its commas.
Counting port NODES therefore called `c` position 1 and would have resolved it
to the wrong formal port of every module instantiated that way. Positions are
counted from the comma separators instead, with a test on that exact shape.

`dv_harness/schemas/env_manifest.schema.json` gains `instances` /
`continuous_assigns` as **non-required** module properties. Additive on purpose:
a manifest written before this extraction existed still validates, so no version
bump is forced for a fact that only grows the parse. (This was found by the real
test suite -- the schema has `additionalProperties: false`, and 6 env-manifest /
evidence-layer tests failed until it was extended.)

### Layer 2 -- `dv_harness/amba_fabric_discovery.py`: the traversal (new, 1619 lines)

A NEW module, per the audit's own framing and the task's carve-out: `connectivity.py`
classifies ONE boundary in isolation; "what is on the other end of this port,
three wrappers and an arbiter away" needs a graph and a traversal over it. It
**composes** connectivity.py's primitives and restates none of them:

| borrowed primitive | used as |
|---|---|
| `classify_amba_protocol()` | the only protocol verdict, re-run per hop -- which is how a bridge crossing is detected |
| `determine_fabric_interface_roles()` | the only role verdict, so a traced endpoint's perspective has the provenance `assert_role_provenance()` demands |
| `classify_bind_tier()` | the only confidence classifier; an unresolved-protocol candidate lands at T4 and goes to the question queue |
| `ALL_AMBA_SIGNAL_NAMES` | the only AMBA signal vocabulary (a new 1-line public alias for the union `_ALL_AMBA_SIGNALS` that already existed -- not a second table) |
| `parse_bind_line()` | the single definition of "a bind statement", used by the no-bind assertion |

**The graph model** is what makes AMBA-7's "do not stop at a transparent wrapper"
structural rather than heuristic: a module boundary port and the parent net wired
to it are one equipotential net class, so a wrapper does not break the net and
simply shows up as another attachment on the same class. Continuous assigns are
deliberately NOT merged -- they are traversable edges with their own hop record,
because merging them would fuse an AXI bundle to an APB bundle inside a bridge
and destroy the invariant AMBA-8 depends on (everything on one class is the same
protocol, so no P1/P2/P3 candidate can sit across a protocol change). Anything
with real logic in it -- mux, arbiter, register slice, CDC, converter, bridge --
breaks the net by construction and must be crossed explicitly, which is where
role classification happens.

Assign traversal is **scope-limited**: strict ancestors when following a bundle
outward from a boundary, self+descendants when asking whether two of a module's
own bundles are internally connected. Without that scoping a bridge's own
internal assign was reachable from outside it and short-circuited the crossing
entirely -- caught and fixed during the build.

Per requirement:

- **AMBA-7 / AMBA-9 / AMBA-10** -- `trace_fabric_port()` plus
  `trace_fabric_slave_interface_to_masters()` /
  `trace_fabric_master_interface_to_slaves()`. Direction is derived from the
  bundle's own AMBA-5 fabric-side role, **never** supplied by the caller;
  calling the slave-side trace on a master-side port raises rather than
  relabelling a destination as a source.
- **AMBA-8** -- `VipPlacementPriority` P1..P4, realised structurally rather than
  by preference-scoring. Two honesty properties: a branch that ended BLOCKED or
  AMBIGUOUS has every candidate demoted to P3 (the boundary is still worth
  watching; calling it the TRUE IP boundary would assert exactly what the branch
  failed to establish), and P4 -- the fabric port itself -- is emitted when
  nothing better was found, so a port is never silently absent from the plan.
  The "do not push VIP beyond" list is recorded as real `push_limits` entries.
- **AMBA-11** -- `ProtocolBridgeCrossing` records both sides, each an independent
  classification of its OWN signal set, so "do not label a downstream APB
  endpoint as AXI" cannot be violated by construction.
- **AMBA-12 / AMBA-13** -- fan-in and fan-out enumerate every branch; none is
  chosen. `MUX_OR_ARBITER` vs `DECODER_OR_INTERCONNECT` is the same structural
  finding named by trace direction.
- **AMBA-14** -- the ten-state `TraceTerminationStatus`, exactly one primary
  status per port, and `assert_unresolved_states_explained()` makes "include
  exact reason and missing evidence" **enforced** rather than requested.

Structural roles are decided from structure; a module NAME can only add a T3
`sub_role_hint` (register slice / CDC / width converter / ID converter /
wrapper), which never changes the structural role, the protocol, or a bind
candidate's tier -- the same "falls to the naming-heuristic tier if unsure"
discipline `connectivity.py`'s T3 already establishes.

**What it refuses to guess is the point.** A module exposing two AMBA bundles
with no visible net-level path between them terminates as AMBIGUOUS (parsed
body -- the correspondence lives in procedural logic a syntax-level parse cannot
see) or TRACE_BLOCKED (module not in the parsed source set), with the missing
evidence named. Neither is rounded up to "bridge" nor down to "endpoint".

## AMBA-30 / AMBA-31 compliance

No `bind` statement is rendered, returned or implied anywhere. The output is a
PLAN: candidate bind LOCATIONS with priorities, tiers, evidence and unresolved
states. `test_no_bind_statement_is_ever_emitted` asserts this against the
module's own source AND its rendered report, using `connectivity.parse_bind_line()`
so there is one definition of "a bind statement" in this repo, not two. The
synthetic SoC fixture lives only inside the test file and contains no bind.

## Tests

`dv_harness_tests/test_amba_fabric_discovery.py` -- 27 tests, every one against
a REAL `verible-verilog-syntax` parse of a synthetic 4-master / 5-slave
mixed-protocol SoC (AXI4 + AHB-Lite + APB4) written to a tmp dir. Never a
hand-built graph object, which would only prove the traversal works on the shape
the test author imagined rather than on what verible really produces. Skipped
(never faked) without verible on PATH.

That one fixture reaches **all ten** AMBA-14 states, so no unresolved state is
an untested branch:

| state | fixture path |
|---|---|
| SOURCE_FOUND | wrapped CPU (`u_cpu_wrap/u_cpu_core`, P1/P2 ladder) and a DMA |
| DESTINATION_FOUND | through a register slice to the DDR controller |
| MULTIPLE_SOURCE | AHB-Lite mux fanning in from two masters |
| MULTIPLE_DESTINATION | AXI decoder fanning out to two SRAMs |
| PROTOCOL_BRIDGE_FOUND | AXI4 -> AXI/APB bridge -> APB4, both sides recorded |
| INTERNAL_ONLY | a fabric port reaching only a fabric-internal monitor |
| TRACE_BLOCKED | an unparsed (`opaque_ip`) module with two AMBA bundles |
| SOURCE_NOT_FOUND | a port reaching the top module's own boundary |
| DESTINATION_NOT_FOUND | an unconnected fabric master port |
| AMBIGUOUS | a parsed two-bundle module with no visible internal path |

**Full run: 593 passed, 0 failed** across every suite importing `connectivity`,
`verible_parser` or the env manifest -- `test_amba_fabric_discovery`,
`test_connectivity`, `test_connectivity_check`, `test_verible_parser`,
`test_env_manifest`, `test_env_manifest_fact_sources`, `test_evidence_db`,
`test_evidence_layer_wiring`, `test_bind_mechanism_generator`,
`test_bind_verification_lint`, `test_blackboard_*`,
`test_confidence_vocabulary_separation`, `test_asset_processing_artifacts`,
`test_amba_fabric_generator`, `test_address_map_verifier`,
`test_protocol_capability`.

## Deliberately NOT done in this step, and why

- **No wiring into `dv_harness/connectivity_check.py`.** The audit correctly
  names it as the natural standing runner for an AMBA fabric-discovery pass, but
  it is being actively modified by a concurrent agent right now (`git status`
  shows it dirty), and a standing-runner integration belongs with AMBA-16/18/19/22's
  artifact emission rather than with the traversal itself. Next step's work.
- **No `scoreboard_matrix` / `address_map`.** `discovered_topology_ids()`
  produces the `masters` / `slaves` flat-ID lists
  `tools/verification_flow/fabric_topology_completeness_gate.py` is shaped
  around, and stops there. Those two keys are AMBA-23/25's, already computed by
  `uvm_generator/amba_fabric_generator.py`'s real `build_scoreboard_matrix()` /
  `compute_address_regions()`; recomputing them here would be exactly the
  duplicate-algorithm failure this module was scoped to avoid. Only endpoints
  whose trace really resolved are listed -- an unresolved port goes to
  `unresolved` and can never quietly become a master or a slave.
- **`.claude/skills/CORE/branch-mapper/SKILL.md`'s "UNTESTED" AMBA label is left
  alone.** It is on a concurrent agent's touch list, and this step delivers
  discovery machinery, not the validated AMBA-fabric pilot that placeholder is
  waiting on. Updating it now would replace one stale claim with another.

## Honest limits, stated rather than implied closed

1. **A syntax-level parse cannot see procedural logic.** An AXI-to-APB bridge
   written as one flat module with only `always` blocks has no net-level path
   between its two bundles and is reported AMBIGUOUS, not PROTOCOL_BRIDGE. That
   is the correct answer for the evidence available, and the fixture tests it
   deliberately -- but it means bridge detection depends on the bridge having
   visible structural connectivity.
2. **Bundle GROUPING is prefix-based** (nothing but a shared prefix says
   `S00_AXI_AWADDR` and `S00_AXI_AWVALID` belong together). This is not the
   name-based protocol classification AMBA-4 forbids: the name only decides
   which GROUP a port joins, and the group's protocol verdict still comes from
   `classify_amba_protocol()` on signal evidence alone. A group whose evidence
   is not AMBA is dropped, so a coincidental prefix cannot manufacture an
   interface.
3. **A SystemVerilog interface-typed port still exposes no signals**, so an
   interface-port fabric boundary classifies as NOT_AMBA and forms no bundle.
   That is `connectivity.py`'s existing, already-disclosed modport gap (AMBA-2),
   inherited unchanged here.
4. **`VIA_SUBINSTANCE` internal-path evidence is conservative toward finding a
   crossing**, and is tiered T3 (requires human confirmation) accordingly rather
   than presented as structural fact.
5. **Generate-block CONDITIONS are not evaluated** -- this is a parser, not an
   elaborator, so a generate-conditional instance is reported as present. Stated
   in `verible_parser.py`'s own docstring so a consumer needing elaboration-time
   truth has to say so rather than assume this settled it.
