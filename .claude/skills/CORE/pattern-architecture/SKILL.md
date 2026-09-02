---
name: pattern-architecture
description: Defines the block/branch_a*/branch_fw/branch_b* task-composition shape a new command.txt/pattern file's SystemVerilog must follow -- fork/join semantics, the recurring trap classes, and what varies vs. stays fixed by test intent. Complements command-generator (which command IDs must exist) with how a generated pattern's internal task composition must be built.
allowed-tools: Read Grep Glob Edit Write PowerShell
---
# Pattern Task-Composition Architecture

This skill answers a different question than `command-generator`: given that a new
`command.txt`/pattern file must be written for some protocol/DUT (any of USB, PCIe,
MIPI CSI-2/DSI, Ethernet, CAN-FD, AMBA4, or another), how must its SystemVerilog task
composition actually be structured, and which trap classes recur because of that
structure. It is protocol-neutral: every rule below is a generic STRUCTURE or CLASS of
problem, stated first in protocol-neutral language, with USB used only as one
labeled, cited illustration where a concrete example helps (per CLAUDE.md's "No
Golden-Reference Content Mining" rule, extended to skill authoring -- see "Relationship
to sibling skills" for why USB is the only real instance this document can currently
cite, and why that does not make the guidance USB-specific).

## 1. The five-layer shape

A pattern is a fixed composition of four task layers, one of which forks into
per-port branches:

```
block                      -- one-shot, chip/SoC-global prologue (BLOCKING)
  |
branch_a0, branch_a1, ...  -- per-port DUT+PHY bring-up, launched non-blocking
  |                            from ONE shared include (does not block the
  |                            include's own return)
branch_fw                  -- per-port firmware/event-service loop, launched
  |                            once, non-blocking, never returns
  |
fork
  branch_b0                  per-port VIP-driven test body
  branch_b1                  per-port VIP-driven test body
  ...
join                       -- NOT join_any (section 2)
  |
verdict / FINAL_CHECK       -- only after every branch_b has genuinely completed
```

**block -- one blocking, non-per-port task.** Whatever the chip-level environment
needs done exactly once before any port-specific work can start: global reset/clock
sequencing, a global-init call, a self-check of the register access path itself. It
runs to completion before anything else starts, because a broken access path and a
broken DUT are indistinguishable if this is skipped.

> USB illustration: `soc_int.svh` is USB's real `block` instance -- STAGE 0 waits for
> the register-access bridges to be ready (`common/soc_int.svh:108-109`), STAGE 1 runs
> the SoC's global-init task (`:127`, "trapvalue MUST be set before GLOBAL_INIT runs"),
> STAGE 2 is an APB self-test (`:189-201`, "without it a broken DUT and a broken access
> path look identical", `:10-11`), STAGE 3 verifies the clock domain the target block
> sits under (`:211-235`). All four stages are one blocking sequence with a documented,
> fixed order (`:9-13`) -- informing the generic rule that `block`'s internal stage
> order is evidence-derived and must not be reordered for convenience.

**branch_a* -- one non-blocking per-port init task per DUT port, launched from a
single shared include, not one call site per pattern.** The shared include does:
(a) any remaining one-shot chip-level flow that must precede per-port work, (b)
launches each port's own bring-up non-blocking (`fork ... join_none` or the
language's equivalent), (c) returns without waiting for any of them. Concurrency
between unrelated ports' `branch_a*` is the default, not an opt-in -- but each
register space a given `branch_a{i}` uses must genuinely belong to that port alone,
or the "unrelated ports don't block each other" assumption is false (section 3.1).

> USB illustration: `common/soc_run.svh:42` is flagged "FIRST STATEMENT OF BRANCH A"
> (a one-shot flow shared by both ports); `:110-116` launch `branch_a0`/`branch_a1`
> (USB's real macro is `USB_FORK_PORT_BRINGUP`, informing this generic guidance) with
> a comment stating explicitly the file "does not wait for any of them" (`:6`). The
> file names the concrete cost of serializing this instead: job 98491 measured port 0
> already trained and at High Speed while the host script was still blocked roughly
> 258 us behind port 1's serial bring-up, and the resulting 155 us of bus silence drove
> the device into an unwanted low-power state it then had to recover from
> (`common/soc_run.svh:99-104`) -- the generic lesson is that accidentally serializing
> independent per-port init doesn't just make the run slower, it can change DUT
> behavior under test.

**branch_fw -- a per-port service loop launched once, non-blocking, never returns.**
It answers whatever the DUT-side firmware/event model needs answered for the rest of
the run to make sense; its internal ARM/WAIT/WAKE/DECODE/CLEAR loop shape is already
generalized in `interrupt-event-dispatch/SKILL.md` -- this section is only about
*where that loop's launch site sits* in the overall pattern shape. It must be
idempotent against being invoked more than once (many callers invoke it explicitly
out of habit), and it must be launched before any branch that could possibly need it.

> USB illustration: `USB_FORK_FW_SERVICE` (USB's real macro name) is launched
> centrally from `common/soc_run.svh:132`, with the ordering reason spelled out at
> `:118-124` ("port 0 can attach and need a responder while port 1's bring-up is still
> running"). It guards against a second launch via its own internal flag (`:126-127`,
> "so a pattern that still calls the fork explicitly ... becomes a harmless no-op
> instead of a second scheduler") -- the generic lesson is that a shared per-port
> service-loop launch site must be safe to invoke from more than one place, because
> callers will.

**branch_b* -- one VIP-driven test body per port, explicitly forked and joined (not
join_any) at the pattern's own top level, each branch independently guarded by that
port's own enable check.** This is the layer a pattern author edits most: the actual
scenario-under-test's stimulus and per-port assertions live here. Two structural
rules recur in every real instance and are not optional style: (a) fork/join, never
join_any, once a branch can complete on its own (section 2); (b) every branch tests
its own port-enable, so a single-port build still gets a completing branch instead of
a hung one.

> USB illustration: `enumeration/usb20_enumeration.txt:57-111` is the canonical
> unmodified case, joined with `join` at line 111, each of `branch_b0`/`branch_b1`
> guarded with `` `USB_PORT_EN(port) `` (`:59`, `:94`) before doing anything else.

**verdict -- runs only after every branch_b has genuinely completed**, which is
exactly what a real `join` guarantees and `join_any` does not (section 2).

> USB illustration: `` `FINAL_CHECK("usb20_enumeration") `` at
> `enumeration/usb20_enumeration.txt:113`, always the last statement, always after the
> `branch_b0`/`branch_b1` `join`.

## 2. join, not join_any -- and why the guarantee expires

This is the single most load-bearing rule in the whole architecture, and it is a
**class of concurrency bug**, not a USB-specific quirk:

> When a task-composition layer forks N independent branches whose completion times
> are NOT guaranteed to be simultaneous or ordered relative to each other, joining on
> "any branch finishes" instead of "every branch finishes" produces a scenario that
> reports success the moment its fastest branch finishes -- even though every other
> branch, including the one carrying the test's real assertions, is still mid-flight.
> The bug is invisible in the log: the run ends cleanly, with zero errors, because
> nothing had a chance to fail yet.

This trap is dangerous specifically because it can be **correct for a while and then
become wrong** as the surrounding architecture evolves:

> USB illustration: `enumeration/usb20_enumeration.txt:44-56` documents this exact
> history. `join_any` "was only ever safe because branch A ended in a forever loop and
> never finished." Once the firmware/event-service responsibility was pulled into its
> own `branch_fw` layer, `branch_a0`/`branch_a1` started completing on their own, and
> `join_any` on the remaining `branch_b0`/`branch_b1` pair would end the pattern at the
> first port's completion -- the file cites a real job as the record of exactly this
> false pass: "job 98520 stopped at 15.32 us with 0 UVM_ERROR and no SvtTestEpilog,
> which reads exactly like a pass" (`:50-51`). Other pattern files in the same suite
> restate the same job number as the standing justification for `join`
> (`link/link_trains_independent_per_port_speed.txt:41-43`,
> `power/usb_dual_port_mixed_speed_concurrent_power.txt:28-29`) -- a single incident,
> reused as the documented reason across an entire suite, rather than re-derived from
> scratch in each file.

**Authoring rule:** when unsure whether a forked group's branches can complete at
different times, default to `join`, and treat `join_any` (or the local language's
equivalent partial-join) as requiring an explicit, written justification. That
justification expires the moment any branch in that fork stops being guaranteed to
run forever -- so it must be revisited whenever the composition of that fork changes,
never written once and trusted indefinitely.

## 3. Recurring trap classes

These are not "USB has these six bugs." They are six *classes* of defect that recur
because of the shape in section 1 -- any protocol's pattern suite built on the same
`block`/`branch_a`/`branch_fw`/`branch_b` shape is exposed to the same classes,
because the classes come from the shape (independent concurrent task groups sharing
resources and depending on each other's completion), not from USB's specific
registers.

**3.1 Two independent task groups can hold conflicting locks on a shared bus
sequencer.** When a DUT-driven task group (e.g. `block`/`branch_a*`, issuing
register writes to bring the DUT itself up) and a VIP-driven task group (e.g.
`branch_b*`, issuing the same style of register writes as part of a test scenario)
both reach the same underlying bus sequencer through *different* named locks/
semaphores, the arbitration layer between them can interleave the two groups'
transactions in an order neither group's author controls -- silently overwriting one
side's write with the other's.

> USB illustration: `enumeration/usb20_enumeration.txt:27-30`: "NO SoC REGISTER
> CONTENT MAY BE ADDED TO A HOST SCRIPT" because USB's real `` `APB_* `` VIP sequences
> and `` `CPUWRITE `` hold different locks on the SAME sequencer, so "UVM arbitration
> interleaves them onto one bus and a USB register write can be silently overwritten."
> Generic fix pattern: identify, from real RTL/VIP evidence, which named locks actually
> gate access to a shared sequencer, and never assume two differently-named task
> groups touching "the same bus" are safely independent just because they're in
> different `fork` branches -- independence of SystemVerilog branches is not
> independence of the underlying arbitration domain. This is the cross-layer instance
> (DUT-driven vs. VIP-driven groups on one sequencer) of the same class
> `branch-mapper/SKILL.md`'s "AMBA M x N Mapping" section already generalizes for
> concurrent APB/AXI access within `block`/`branch_a*`.

**3.2 A stage-ordering dependency must be verified per-port, not globally.** When
branch B's first action depends on state that branch A's per-port init produces, that
dependency must be checked against *that port's own* signal/register, not a single
pattern-wide flag -- in a multi-port build, one port's readiness says nothing about
another's.

> USB illustration: `enumeration/usb20_enumeration.txt:64-67`: link-up must precede
> enumeration "so enumeration cannot start before DSTS.CONNECTSPD reports this port's
> built speed ... The stage reads the port's own DEVSPD, so a mixed SPEED0/SPEED1
> build polls for a different value on each port."

**3.3 A shared destination variable turns two genuinely concurrent reads into a
silent race.** Once two branches issue register *reads* concurrently on different
buses (because they hold different locks, per 3.1's arbitration split), a read's
*destination* becomes the new hazard: a write carries its data as an argument and has
nowhere to collide, but a read has to land somewhere -- if both branches' reads target
the same shared variable, the branch that finishes second silently clobbers the
first's result with no error raised anywhere.

> USB illustration: `common/soc_run.svh:174-181`: "a read has a DESTINATION, and
> `pat_rdata` is one variable shared by every `` `CPUREAD4B `` and `` `AXI_READ4B ``
> in the pattern. Two branches reading on two buses into it is a silent race ... A
> BRANCH READING ON ANOTHER BUS MUST USE ITS OWN [destination variable]." Generic
> lesson: any language/VIP combination that lets two concurrent branches target one
> shared variable for their result has this hazard the moment concurrency is
> introduced -- the fix is always one destination per independently-completing
> branch, never "hope the branches don't finish close together."

**3.4 Enabling a resource before it is configured silently drops its content.** When
a per-port bring-up sequence both configures a sub-resource (an endpoint, a channel,
a queue) and separately enables the whole resource set, doing the enable step before
the pattern's own configuration lands means the resource comes up
enabled-but-unconfigured -- it participates in whatever it does by default (often:
reports nothing, moves no data) with no error, because "enabled" and "configured
correctly" are different bits.

> USB illustration: `common/soc_run.svh:76-89`: without the pause point USB's real
> `` `USB_EP_CFG_DEFERRED `` flag creates, a pattern writing its endpoint
> configuration after the whole bring-up returned would violate the databook's
> documented order (configure before enable) because the enable stage already wrote
> DALEPENA -- "the cost is: configured, enabled, moves no data, reports nothing."
> Generic authoring rule: any shared per-port bring-up include that both configures
> and enables sub-resources needs an explicit pause point a pattern can opt into when
> it supplies its own sub-resource configuration, so "configure" always precedes
> "enable" for content the pattern adds.

**3.5 A forked background sequence without its own explicit join is a silent early
pass.** Dispatching a VIP sequence into the background (non-blocking, to run
concurrently with something else) and reaching the verdict step without an explicit
wait for that specific dispatch's completion produces a pass verdict while the
dispatched sequence is still mid-flight. This is narrower than section 2's
whole-pattern join/join_any rule, but it is the same underlying class (declaring
success before concurrent work is actually done), and it recurs inside `branch_b*`
bodies themselves, not just at the top-level fork.

> USB illustration: `transfer/usb_dual_port.txt:229-231`: "`` `WAIT_SEQ_ALL_OK `` IS
> THE POINT OF FAILURE IF IT IS EVER DROPPED ... A forked sequence is still running
> when the call returns, so a round without its join reaches FINAL_CHECK mid-transfer
> and reports Passed." Generic rule: every non-blocking dispatch of concurrent
> stimulus needs a paired, explicit "wait for this dispatch" call before the branch
> that dispatched it is allowed to report a result -- the pairing is a property of
> the dispatch call itself, not something the surrounding `fork`/`join` at a higher
> layer can substitute for.

**3.6 A single pattern-wide "is this port my subject" gate silently skips a
divergent port.** A per-port branch body that gates its own execution on comparing
that port's actual configuration against ONE pattern-wide expected value (rather
than testing unconditionally, or comparing against that port's own
independently-derived expectation) will silently skip any port whose real build
diverges from that one expected value -- turning a multi-port mixed-configuration run
into an accidentally-single-port run with no error, just a quiet "skipped" log line.

> USB illustration: `link/link_trains_independent_per_port_speed.txt:8-15`
> documents this as a real, previously-shipped gap: four sibling patterns each
> `` `define `` a single pattern-wide wanted value and compare it "PER PORT," so "in a
> mixed build ... the port that disagrees with the fixed want is skipped" -- silently,
> not as a failure. The fix pattern this file demonstrates (`:50-68`) is to make each
> port branch unconditionally its own subject at whatever its own build actually
> produced, never gated on a single shared "want." The same fix is reused for a
> different axis in `power/usb_dual_port_mixed_speed_concurrent_power.txt:9-25` -- a
> second, independently confirmed instance of the same class. Generic authoring rule:
> a per-port branch's "is this port relevant" test must never collapse multiple
> ports' independent configurations into a single pattern-wide comparison value
> unless the pattern's own declared intent is a fixed, uniform configuration across
> every port.

## 4. What varies vs. what stays fixed by test intent

**Stays fixed, in every real instance:**
- The four-layer ordering: `block` -> `branch_a*` (inside the shared bring-up
  include) -> `branch_fw` -> `fork`/`join` of `branch_b*` -> verdict.
- `join`, never `join_any`, on the `branch_b*` fork -- with the reasoning (section 2)
  cited, not re-derived, file to file once established for a suite.
- Each `branch_b*` (or its substitute, see below) independently port-enable-guarded.
- A shared arbitration-policy reason for concurrent bus access across ports is
  *cited*, not re-justified, once established for a sequence of sibling patterns.

**Varies with test intent:**
- **Whether branch_b* is split per port at all.** The default is one branch per
  port. A pattern whose actual subject is *cross-port ordering itself* may
  deliberately collapse multiple ports into a single branch instead -- USB
  illustration: `transfer/usb_dual_port.txt:90-99` collapses both ports into one
  `branch_b` because "a round arms BOTH ports and only then fires BOTH, so the two
  ports' host scripts cannot be split ... that ordering across the ports is what the
  pattern tests" (`:35-37`, labeled explicitly in the file's own header). This is a
  deliberate, explicitly-labeled deviation from the default shape, not an
  inconsistency -- the generic lesson is that the shape is a strong default, not an
  inviolable rule, and any deviation must be labeled as deliberate with the reason
  the test needs it, exactly as this file does.
- **What lives inside each branch_b*.** Direct macro/task calls in the simple case,
  or an `` `include `` of a shared per-port body file parametrized by preprocessor
  defines set immediately before the include and undefined immediately after, when
  the same per-port body logic is reused across several sibling patterns -- USB
  illustration: `power/usb_dual_port_mixed_speed_concurrent_power.txt:70-74`,`:89-93`
  (`` `define USB_BODY_PORT p `` / `` `include "usb_power_body.svh" `` /
  `` `undef USB_BODY_PORT ``).
- **Whether a shared per-port body file is used at all, or bypassed with inline
  logic.** A shared body file is a convenience, not a requirement -- a pattern
  author must check what a shared body transitively pulls in before reusing it, not
  just what it appears to do at the call site. USB illustration:
  `link/link_trains_independent_per_port_speed.txt:17-21` deliberately does NOT
  `` `include `` the usual shared per-port body file, because that file itself
  `` `include ``s a second file carrying the single-pattern-wide "want" gate from
  section 3.6 -- reusing the shared body would silently reimpose the exact gap this
  pattern exists to bypass.
- **Extra pause-point defines set before the shared bring-up include**, when a
  pattern supplies its own sub-resource configuration content (section 3.4's
  configure-before-enable flag).

## 5. Pre-flight checklist before writing a new pattern file

1. Identify the four layers for this protocol/DUT from real evidence, using
   `branch-mapper/SKILL.md`'s "Initialization Task Hierarchy" and "Real-World
   Reference Mapping" sections as the taxonomy -- this skill assumes that taxonomy
   and focuses on the authoring mechanics on top of it.
2. Confirm whether the new scenario fits the default one-branch_b-per-port shape, or
   whether its actual subject is cross-branch ordering (section 4) -- if the latter,
   the deviation must be labeled and justified in the file's own header comment, not
   left implicit.
3. `join`, not `join_any`, unless every branch in the fork is provably guaranteed
   never to return on its own -- and treat that guarantee as expiring the moment the
   fork's composition changes (section 2).
4. For every stage-ordering dependency inside a per-port branch, confirm the
   readiness check reads THAT port's own state, never a shared flag (sections 3.2,
   3.6).
5. For every concurrent read across two independently-locked task groups, confirm
   each group has its OWN destination variable -- never a variable shared across
   branches that can complete at different times (section 3.3).
6. For every non-blocking dispatch of concurrent VIP stimulus, confirm there is a
   paired explicit wait before that branch reports its own result (section 3.5).
7. For every shared per-port bring-up/body include being reused, check what it
   transitively includes, not just its direct effect at the call site (section 4) --
   and check whether it needs a configure-before-enable pause point for any
   sub-resource content the new pattern supplies (section 3.4).
8. Source branch-B/VIP-driven content from VIP examples/user manual/source/class
   reference, and branch-A/branch_fw-driven content from DUT RTL/PHY docs/
   programming guide -- already required by `vip-scenario-branch` and
   `interrupt-event-dispatch`, restated here because it governs the CONTENT that
   fills the skeleton this skill describes, not just edits to existing files (per
   CLAUDE.md's "No Golden-Reference Content Mining," this applies to writing
   brand-new pattern content exactly as it does to modifying existing files).
9. Check `.dv-workflow/command_inventory.csv` for change-impact before and after any
   generator/schema change that could affect an existing pattern -- already codified
   in `command-inventory/SKILL.md`'s "Change-Impact Check."

## Relationship to sibling skills

| Skill | Covers | Does NOT cover |
|---|---|---|
| `branch-mapper` | The four-layer taxonomy (what `block`/`branch_a*`/`branch_fw`/`branch_b*` each mean), N:M mapping records, AMBA shared-resource arbitration policy | How to actually write the `fork`/`join` SystemVerilog inside a new pattern file |
| `interrupt-event-dispatch` | `branch_fw`'s internal ARM/WAIT/WAKE/DECODE/CLEAR loop shape, per-port service-loop parallelism, two generic W1C/mask rules | Where `branch_fw`'s launch site sits relative to `block`/`branch_a*`/`branch_b*` in one pattern file, or anything about `branch_b*`'s own composition |
| `vip-scenario-branch` | `branch_b*` as a traceability/record layer (VP_ID -> SCENARIO_ID -> ... -> VIP_SEQUENCE), VIP-sourcing discipline | The concrete `fork`/`join`-not-`join_any` mechanics, or any of the six trap classes in section 3 |
| `command-inventory` | Existing `command.txt` as a reusable/backward-compatible capability baseline, change-impact checking | Authoring guidance for a scenario's internal task composition |
| `command-generator` | Which command IDs must exist (vPlan-gap-driven), `command_mapping.csv` maintenance, DE/DV command spelling | How a generated pattern's internal SystemVerilog task composition must be built -- see this skill |

**This skill (`pattern-architecture`) is the missing piece**: no other skill tells an
author how to compose a NEW pattern file's `fork`/`join` structure, which structural
rules are load-bearing (sections 2-3) vs. which vary by intent (section 4), or what
to check before writing one (section 5).

**On the USB illustrations throughout this file:** every generic point above was
distilled by reading USB's real, validated pattern suite in
`D:\DV\Task\DV_Agent_Harness_L5\USB_UVM_Handoff\uvm\tb\patterns\` (`common/soc_int.svh`,
`common/soc_run.svh`, `enumeration/usb20_enumeration.txt`,
`transfer/usb_dual_port.txt`, `link/link_trains_independent_per_port_speed.txt`,
`power/usb_dual_port_mixed_speed_concurrent_power.txt`), currently the only real,
validated instance of this architecture anywhere in this repo. USB macro/register
names appear only inside boxes explicitly marked "USB illustration" as a labeled
concrete example of a generic point already stated in protocol-neutral language first
-- they are never Harness vocabulary, and a new protocol's pattern suite must derive
its own actual macro/register names from that protocol's own VIP/RTL evidence (per
checklist item 8), never reuse USB's names. Per CLAUDE.md's "No Golden-Reference
Content Mining" rule, this skill's job stops at the generic STRUCTURE and CLASS of
problem; it must never be read as license to copy USB pattern-file CONTENT into
another protocol's pattern.
