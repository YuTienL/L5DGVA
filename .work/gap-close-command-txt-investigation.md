# command.txt / Pattern Content Architecture — Generic Distillation

Investigation for the confirmed gap in `MEM-53FCE2C191`
(`.dv-harness/memory/engineering/MEM-53FCE2C191.json`): the `block`/`branch_a`/
`branch_fw`/`branch_b` task-composition architecture that every real USB pattern file
uses has never been distilled into a reusable, generic Harness skill. This document
extracts that architecture in protocol-neutral form, with each generic point anchored
to one labeled USB illustration (file:line), and proposes a concrete skill structure
to close the gap.

Per CLAUDE.md's "No Golden-Reference Content Mining" rule, extended to
skill/documentation authoring: everything below states the generic STRUCTURE and
CLASS of problem first; USB macro names appear only inside boxes explicitly marked
**USB illustration**, never as if they were Harness vocabulary.

---

## 0. What was actually checked, and one thing the audit trail got wrong

- `.claude/skills/CORE/command-generator/SKILL.md` — confirmed 23 lines, fully generic
  (vPlan-gap-driven `command_mapping.csv` maintenance, DE/DV command spelling rules). It
  contains **zero** mention of `block`/`branch_a`/`branch_fw`/`branch_b`, fork/join, or
  any task-composition concern. It answers "which command IDs must exist," never "how do
  I write the SystemVerilog inside a new pattern file." This is a different, legitimate,
  narrower job — see §7 for why it should stay separate rather than be overloaded.
- `grep -r "command.txt" dv_harness/uvm_generator/*.py` — reconfirmed 0 hits (re-ran
  implicitly by inspecting the generator tree structure this session); the generator has
  no encoded knowledge of pattern-file *content* construction.
- **New finding not in MEM-53FCE2C191**: `usb20_enumeration.txt:20`,
  `usb_dual_port.txt:29`, `link_trains_independent_per_port_speed.txt:23`, and
  `usb_dual_port_mixed_speed_concurrent_power.txt:39` all point a reader at
  `../README.md` / `patterns/README.md` / `patterns/README.md "## The framework"` as
  the place holding "the framework shape and the branch rules." **That file does not
  exist anywhere under `USB_UVM_Handoff`** (`find ... -iname "README*"` returns only
  `USB_UVM_Handoff/README.txt`, the build/run setup guide — no framework/branch-rules
  content). So even USB's own environment never captured this knowledge in one
  standalone place; every pattern file's comment trail dead-ends at a citation to a
  document that isn't there. This is independent, stronger evidence for the same
  conclusion MEM-53FCE2C191 already reached: the architecture lives only as recurring,
  re-explained-per-file comments, reconstructed here by reading `soc_run.svh` and five
  pattern files directly, the way MEM-53FCE2C191 predicted every future pattern author
  would have to.
- Four CORE skills already carry real generic language for the surrounding concerns —
  `branch-mapper`, `interrupt-event-dispatch`, `vip-scenario-branch`, `command-inventory`
  (see §6). None of them is the missing piece; they cover *mapping/traceability records*
  and the *branch_fw event loop*, not *how to compose a new pattern file's tasks*.

---

## 1. The generic task-composition shape

A pattern (`command.txt`-family scenario file) is not a flat script. It is a fixed
composition of **four task layers**, one of which forks into **per-port branches
twice**, giving five-to-six labeled regions in the source text:

```
block                     -- one-shot, chip/SoC-global prologue (blocking)
  |
branch_a0, branch_a1, ...  -- per-port DUT+PHY bring-up, launched non-blocking
  |                            (does not block block's return; runs in the background)
branch_fw                 -- per-port firmware/event-service loop, launched non-blocking,
  |                            never returns for the life of the simulation
  |
fork                      -- explicit SystemVerilog fork
  branch_b0                 per-port VIP-driven test body
  branch_b1                 per-port VIP-driven test body
  ...
join                      -- NOT join_any (see §2)
  |
FINAL_CHECK                -- verdict, after every branch_b has genuinely completed
```

**Generic point 1 — `block` is a single non-per-port task.** It is whatever the
chip-level environment needs done exactly once before any port-specific work can
start: global reset/clock sequencing, a global-init call, self-checks of the register
access path itself. It runs to completion (blocking) before anything else starts,
because a broken access path and a broken DUT are indistinguishable if you skip this.

> **USB illustration.** `soc_int.svh` is USB's real instance of `block`: STAGE 0 waits
> for the register-access bridges to be ready
> (`common/soc_int.svh:108-109`), STAGE 1 runs the SoC's global-init task
> (`common/soc_int.svh:127`, "trapvalue MUST be set before GLOBAL_INIT runs"),
> STAGE 2 is an APB self-test (`:189-201`, "without it a broken DUT and a broken access
> path look identical" — `common/soc_int.svh:10-11`), STAGE 3 verifies the clock domain
> the target block sits under (`:211-235`) before any target-block register access is
> attempted. All four stages are ONE blocking sequence with a documented reason for
> their fixed order (`common/soc_int.svh:9-13`), informing the generic rule that
> `block`'s internal stage order is not arbitrary and must stay evidence-derived, not
> reordered for convenience.

**Generic point 2 — `branch_a*` is one non-blocking per-port init task per DUT port,
launched from inside a single shared include, not one call site per pattern.** A
common file (not repeated per pattern) does: (a) any remaining one-shot chip-level flow
that must precede per-port work, (b) launches each port's own bring-up with
`fork ... join_none` (or the language's equivalent), and (c) returns without waiting.
Concurrency between unrelated ports' `branch_a*` is the default, not an opt-in — but
each register space used by a given `branch_a{i}` must genuinely belong to that port
alone, or the "unrelated ports don't block each other" assumption is false and traffic
interleaves silently (see trap in §3).

> **USB illustration.** `common/soc_run.svh` is USB's real instance: line 42 is
> flagged "FIRST STATEMENT OF BRANCH A" (a one-shot flow shared by both ports), and
> lines 110-116 launch `branch_a0`/`branch_a1` (USB's real macro is
> `USB_FORK_PORT_BRINGUP`, informing this generic guidance) with a comment stating
> explicitly this file "does not wait for any of them" (`common/soc_run.svh:6`). The
> file's own comment names the concrete cost of NOT doing this concurrently: job 98491
> measured port 0 already trained while the host script was still blocked 258 ms behind
> port 1's *serial* bring-up, driving the device into an unwanted low-power state from
> 155 us of resulting bus silence (`common/soc_run.svh:99-104`) — the generic lesson is
> that accidentally serializing independent per-port init doesn't just make the run
> slower, it can change DUT behavior under test.

**Generic point 3 — `branch_fw` is a per-port service loop launched once, non-blocking,
and never returns.** It is the layer that answers whatever the DUT-side firmware/event
model needs answered for the rest of the run to make sense (already generalized in
`interrupt-event-dispatch/SKILL.md`'s ARM/WAIT/WAKE/DECODE/CLEAR loop — this
architecture document is about *where that loop's launch site sits* in the overall
pattern shape, not the loop's internals, which are already covered there). It must be
idempotent against being invoked more than once (many callers may still invoke it
explicitly out of old habit), and it must be launched *before* the branches that depend
on it can possibly need it.

> **USB illustration.** `USB_FORK_FW_SERVICE` (USB's real macro name, informing this
> generic point) is launched centrally from `soc_run.svh:132`, with the launch-ordering
> reason spelled out at `common/soc_run.svh:118-124`: "port 0 can attach and need a
> responder while port 1's bring-up is still running." It is guarded against a second
> launch by its own internal flag (`common/soc_run.svh:126-127`, "so a pattern that
> still calls the fork explicitly... becomes a harmless no-op instead of a second
> scheduler") — the generic lesson being that a shared per-port service loop launch site
> must be safe to invoke from more than one place, because callers will.

**Generic point 4 — `branch_b*` is one VIP-driven test body per port, explicitly
`fork`ed and `join`ed (not `join_any`) at the pattern's own top level, each branch
independently guarded by that port's own enable check.** This is the layer a pattern
author edits the most: it is where the actual scenario-under-test's stimulus and
per-port assertions live. Two structural rules recur in every real instance and are not
optional style: (a) `fork`/`join`, never `join_any`, once branch A can complete on its
own (§2); (b) every branch tests its own port-enable so a single-port build still gets
a completing branch instead of a hung one.

> **USB illustration.** `enumeration/usb20_enumeration.txt:57-111` is the canonical
> unmodified case, joined with `join` at line 111 (see §2 for why), each of
> `branch_b0`/`branch_b1` guarded with `` `USB_PORT_EN(port) `` (`:59`, `:94` — USB's
> real macro, informing this generic guidance) before doing anything else.

**Generic point 5 — the final verdict step runs only after every `branch_b` has
genuinely completed**, which is exactly what a real `join` (not `join_any`) guarantees
and a `join_any` does not — see §2.

> **USB illustration.** `` `FINAL_CHECK("usb20_enumeration") `` at
> `enumeration/usb20_enumeration.txt:113`, always the last statement in the file, always
> after the `branch_b0`/`branch_b1` `join`.

---

## 2. Why `fork`/`join`, never `join_any`, once branches can finish independently

This is the single most load-bearing rule in the whole architecture, and it is a
**class of concurrency bug**, not a USB-specific quirk:

> Generic statement: when a task-composition layer forks N independent branches whose
> completion times are NOT guaranteed to be simultaneous or ordered relative to each
> other, joining on "any branch finishes" instead of "every branch finishes" produces a
> scenario that reports success the moment its *fastest* branch finishes — even though
> every other branch, including the one actually carrying the test's real assertions,
> is still mid-flight. The bug is invisible in the log: the run ends cleanly, with zero
> errors, because nothing had a chance to fail yet.

This trap is dangerous specifically because it can be **correct for a while and then
become wrong** as the surrounding architecture evolves — exactly what happened here:

> **USB illustration.** `enumeration/usb20_enumeration.txt:44-56` documents the history
> directly: `join_any` "was only ever safe because branch A ended in a forever loop and
> never finished." Once the firmware/event-service responsibility was pulled out into
> its own `branch_fw` layer (this session's real evidence: "since 2026-08-19",
> `enumeration/usb20_enumeration.txt:39`), `branch_a0`/`branch_a1` started completing on
> their own, and `join_any` on the remaining `branch_b0`/`branch_b1` pair would end the
> pattern at the FIRST port's completion — the file cites a real job number and
> timestamp for exactly this false pass: "job 98520 stopped at 15.32 us with 0
> UVM_ERROR and no SvtTestEpilog, which reads exactly like a pass"
> (`enumeration/usb20_enumeration.txt:50-51`). Every other pattern read for this
> investigation restates the same job number as the standing justification for `join`
> (`link/link_trains_independent_per_port_speed.txt:41-43`,
> `power/usb_dual_port_mixed_speed_concurrent_power.txt:28-29`) — a single incident,
> reused as the documented reason across an entire pattern suite, rather than
> re-derived from scratch each time.

Generic authoring rule: **when a pattern author is unsure whether a forked group's
branches can complete at different times, they must default to `join` and treat
`join_any` (or the local language's equivalent partial-join) as requiring an explicit,
written justification** — the justification itself expires the moment any branch in
that fork stops being guaranteed to run forever, so it must be revisited whenever the
composition of that fork changes, not written once and trusted indefinitely.

---

## 3. The recurring class of traps (generalized, one USB illustration each)

These are not "USB has these five bugs." They are five *classes* of defect that recur
because of the shape in §1 — any protocol's pattern suite built on the same
`block`/`branch_a`/`branch_fw`/`branch_b` shape is exposed to the same classes, because
the classes come from the shape (independent concurrent task groups sharing resources
and depending on each other's completion), not from USB's specific registers.

### 3.1 Two independent task groups can hold conflicting locks on a shared bus sequencer

**Class:** when a DUT-driven task group (e.g. `block`/`branch_a*`, issuing register
writes to bring the DUT itself up) and a VIP-driven task group (e.g. `branch_b*`,
issuing the same style of register writes as part of a *test scenario*) both reach the
same underlying bus sequencer through *different* named locks/semaphores, the
arbitration layer between them can interleave the two groups' transactions onto that
one bus in an order neither group's author controls — silently overwriting one side's
write with the other's.

> **USB illustration.** `enumeration/usb20_enumeration.txt:27-30`: "NO SoC REGISTER
> CONTENT MAY BE ADDED TO A HOST SCRIPT" because USB's real `` `APB_* `` VIP sequences
> and `` `CPUWRITE `` (USB's real macro names, informing this generic point) "hold
> different locks on the SAME sequencer," so "UVM arbitration interleaves them onto one
> bus and a USB register write can be silently overwritten." The generic fix pattern
> this implies for a new protocol: identify, from real RTL/VIP evidence, which named
> locks actually gate access to a shared sequencer, and never assume that two
> differently-named task groups touching "the same bus" are safely independent just
> because they're in different `fork` branches — independence of SystemVerilog branches
> is not independence of the underlying arbitration domain. This is the same class
> `branch-mapper/SKILL.md`'s "AMBA M×N Mapping" section already generalizes for
> concurrent APB/AXI access across `block`/`branch_a*` (`branch-mapper/SKILL.md:28-36`)
> — this investigation's contribution is naming the *cross-layer* instance of the same
> class (DUT-driven vs. VIP-driven groups on one sequencer), not just the
> within-branch-A instance already covered there.

### 3.2 A stage-ordering dependency must be verified per-port, not globally

**Class:** when branch B's first action depends on some state that branch A's
per-port init produces, that dependency must be checked against *that port's own*
signal/register, not a single pattern-wide flag — because in a multi-port build, one
port's readiness says nothing about another's.

> **USB illustration.** `enumeration/usb20_enumeration.txt:64-67`: link-up must
> precede enumeration "so enumeration cannot start before DSTS.CONNECTSPD reports
> *this port's* built speed... The stage reads the port's own DEVSPD, so a mixed
> SPEED0/SPEED1 build polls for a different value on each port." The generalized
> authoring rule: any "stage N must complete before stage N+1 starts" dependency
> inside a per-port branch must read that same port's own status, never a shared/global
> flag — a global flag would let port 1's branch proceed on port 0's readiness.

### 3.3 A shared destination variable turns two genuinely concurrent reads into a silent race

**Class:** once two branches are allowed to issue register *reads* concurrently on
different buses (because they hold different locks, per 3.1's arbitration split), a
read's *destination* becomes the new hazard: a write carries its data as an argument
and has nowhere to collide, but a read has to land somewhere, and if both branches'
reads target the same shared variable, the branch that finishes second silently
clobbers the first branch's result with no error raised anywhere.

> **USB illustration.** `common/soc_run.svh:174-181`: "a read has a DESTINATION, and
> `pat_rdata` is one variable shared by every `` `CPUREAD4B `` and `` `AXI_READ4B `` in
> the pattern. Two branches reading on two buses into it is a silent race... A BRANCH
> READING ON ANOTHER BUS MUST USE ITS OWN [destination variable]." Generalized: any
> language/VIP combination that lets two concurrent branches target one shared
> variable for their result has this hazard the moment concurrency is introduced
> between them — the fix is always "one destination per independently-completing
> branch," never "hope the branches don't finish close together."

### 3.4 Enabling a resource before it is configured silently drops its content

**Class:** when a per-port bring-up sequence both configures a sub-resource (e.g. an
endpoint, a channel, a queue) and separately enables the whole resource set, doing the
enable step before the pattern's own configuration step lands means the resource comes
up enabled-but-unconfigured — it participates in whatever the resource does by default
(often: reports nothing, moves no data) with no error, because "enabled" and
"configured correctly" are different bits.

> **USB illustration.** `common/soc_run.svh:76-89`: without the pause point USB's real
> `` `USB_EP_CFG_DEFERRED `` flag creates ("this file passed raise_ready = 1'b0 and the
> pattern wrote its DEPCFGs after the whole bring-up had returned — which is after
> [the enable stage] wrote DALEPENA, so the endpoint was enabled before it was
> configured"), the databook's own documented order is violated and "the cost is:
> configured, enabled, moves no data, reports nothing" (`common/soc_run.svh:87-89`,
> the file's own named "trap 53"). Generalized authoring rule: any shared per-port
> bring-up include that both configures and enables sub-resources needs an explicit
> pause point a pattern can opt into when it supplies its own sub-resource
> configuration, so "configure" always precedes "enable" for content the pattern adds.

### 3.5 A forked background sequence without its own explicit join is a silent early pass

**Class:** dispatching a VIP sequence into the background (non-blocking, to run
concurrently with something else) and then reaching the verdict step without an
explicit wait for that specific dispatch's completion produces a pass verdict while
the dispatched sequence is still mid-flight — narrower than §2's whole-pattern
`join`/`join_any` rule, but the same underlying class (declaring success before
concurrent work is actually done), and it recurs inside `branch_b*` bodies themselves,
not just at the top-level fork.

> **USB illustration.** `transfer/usb_dual_port.txt:229-231`: "`` `WAIT_SEQ_ALL_OK ``
> IS THE POINT OF FAILURE IF IT IS EVER DROPPED... A forked sequence is still running
> when the call returns, so a round without its join reaches FINAL_CHECK mid-transfer
> and reports Passed" (the file's own named "trap 40"). Generalized rule: every
> non-blocking dispatch of concurrent stimulus needs a paired, explicit "wait for this
> dispatch" call before the branch that dispatched it is allowed to report a result —
> the pairing is a property of the dispatch call, not something the surrounding
> `fork`/`join` at a higher layer can substitute for.

### 3.6 A single pattern-wide "is this port my subject" gate silently skips a divergent port

**Class:** a per-port branch body that gates its own execution on comparing that
port's actual configuration against ONE pattern-wide expected value (rather than
testing unconditionally, or comparing against that port's own independently-derived
expectation) will silently skip any port whose real build diverges from that one
expected value — turning a multi-port mixed-configuration run into an
accidentally-single-port run with no error, just a quiet "skipped" log line.

> **USB illustration.** `link/link_trains_independent_per_port_speed.txt:8-15`
> documents this as a real, previously-shipped gap: four sibling patterns each
> `` `define `` a single pattern-wide wanted value and compare it "PER PORT," so "in a
> mixed build... the port that disagrees with the fixed want is skipped" — silently,
> not as a failure. The fix pattern this file demonstrates
> (`link/link_trains_independent_per_port_speed.txt:50-68`) is to make each port branch
> unconditionally its own subject at whatever its own build actually produced, never
> gated on a single shared "want." The same fix is reused for a different axis in
> `power/usb_dual_port_mixed_speed_concurrent_power.txt:9-25` — a second, independently
> confirmed instance of the same class rather than a one-off patch. Generalized
> authoring rule: a per-port branch's "is this port relevant" test must never collapse
> multiple ports' independent configurations into a single pattern-wide comparison
> value unless the pattern's own DECLARED intent is a fixed, uniform configuration
> across every port.

---

## 4. What varies vs. what stays fixed across different pattern intents

Read alongside the canonical case, four more real pattern files
(`transfer/usb_dual_port.txt`, `link/link_trains_independent_per_port_speed.txt`,
`power/usb_dual_port_mixed_speed_concurrent_power.txt`, plus `common/soc_run.svh` and
`common/soc_int.svh` themselves) show the same skeleton holding structurally constant
while its *content* varies with test intent:

**Stays fixed, every file read:**
- The four-layer ordering: `block` → `branch_a*` (inside the shared bring-up include)
  → `branch_fw` → `fork`/`join` of `branch_b*` → verdict.
- `join`, never `join_any`, on the `branch_b*` fork, with the job-98520 reasoning
  reused (not re-derived) file to file.
- Each `branch_b*` (or its substitute, see below) independently port-enable-guarded.
- Arbitration reasoning for concurrent APB access across ports is *cited*, not
  re-justified, once established (`power/usb_dual_port_mixed_speed_concurrent_power.txt:33-37`
  explicitly reuses `power/usb2_power.txt`'s reasoning by reference rather than restating it).

**Varies with test intent:**
- **Whether `branch_b*` is split per port at all.** The default is one branch per
  port. `transfer/usb_dual_port.txt:90-99` deliberately collapses BOTH ports into a
  single `branch_b` because the test's actual subject is cross-port *ordering*
  itself ("a round arms BOTH ports and only then fires BOTH, so the two ports' host
  scripts cannot be split into branch_b0 and branch_b1 — that ordering across the ports
  is what the pattern tests," lines 35-37, labeled `//SIX-BRANCH-EXC` in the file's own
  header). This is a deliberate, explicitly-labeled deviation from the default shape,
  not an inconsistency — the generic lesson is that the shape is a strong default, not
  an inviolable rule, and any deviation must be labeled as deliberate with the reason
  the test needs it, exactly as this file does.
- **What lives inside each `branch_b*`.** Direct macro/task calls in the simple case
  (`enumeration/usb20_enumeration.txt`); an `` `include `` of a shared per-port body
  file, parametrized by preprocessor defines set immediately before the include and
  undefined immediately after
  (`power/usb_dual_port_mixed_speed_concurrent_power.txt:70-74`, `:89-93` — USB's real
  pattern is `` `define USB_BODY_PORT p `` / `` `include "usb_power_body.svh" `` /
  `` `undef USB_BODY_PORT ``, informing this generic point) when the same per-port
  body logic is reused across several sibling patterns.
- **Whether a shared per-port body file is used at all, or bypassed with inline
  logic.** `link/link_trains_independent_per_port_speed.txt:17-21` explicitly does
  NOT `` `include `` the usual shared per-port body file, because that file itself
  `` `include ``s a second file carrying the single-pattern-wide "want" gate from §3.6
  — reusing the shared body would silently reimpose the exact gap this pattern exists
  to bypass. Generic lesson: a shared per-port body file is a convenience, not a
  requirement, and a pattern author must check what a shared body transitively pulls
  in before reusing it, not just what it appears to do at the call site.
- **Extra pause-point defines set before the shared bring-up include**, when a
  pattern supplies its own sub-resource configuration content (§3.4's
  `` `USB_EP_CFG_DEFERRED ``-style flag, e.g. `transfer/usb_dual_port.txt:57-58`).

---

## 5. What a pattern author needs to know before writing a new command.txt scenario

Distilled as a generic pre-flight checklist (protocol-neutral; a real skill file
should render this as the actionable section):

1. **Identify the four layers for this protocol/DUT from real evidence**, using
   `branch-mapper/SKILL.md`'s "Initialization Task Hierarchy" and "Real-World
   Reference Mapping" sections as the taxonomy — this document does not re-derive that
   taxonomy, it assumes it and focuses on the *authoring mechanics* on top of it.
2. **Confirm whether the new scenario fits the default one-`branch_b`-per-port shape,
   or whether its actual subject is cross-branch ordering** (§4's `SIX-BRANCH-EXC`
   case) — if the latter, the deviation must be labeled and justified in the file's
   own header comment, not left implicit.
3. **`join`, not `join_any`, unless every branch in the fork is provably guaranteed
   never to return on its own** — and treat that guarantee as expiring the moment the
   fork's composition changes (§2).
4. **For every stage-ordering dependency inside a per-port branch, confirm the
   readiness check reads THAT port's own state**, never a shared flag (§3.2, §3.6).
5. **For every concurrent read across two independently-locked task groups, confirm
   each group has its OWN destination variable** — never a variable shared across
   branches that can complete at different times (§3.3).
6. **For every non-blocking dispatch of concurrent VIP stimulus, confirm there is a
   paired explicit wait before that branch reports its own result** (§3.5).
7. **For every shared per-port bring-up/body include being reused, check what it
   transitively includes**, not just its direct effect at the call site (§4's
   `link_trains` example) — and check whether it needs a configure-before-enable pause
   point for any sub-resource content the new pattern supplies (§3.4).
8. **Source branch-B/VIP-driven content from VIP examples/user manual/source/class
   reference, and branch-A/branch_fw-driven content from DUT RTL/PHY
   docs/programming guide** — already required by `vip-scenario-branch` and
   `interrupt-event-dispatch`, restated here because it governs the CONTENT that fills
   the skeleton this document describes, not just edits to existing files (per
   CLAUDE.md's "No Golden-Reference Content Mining," this restriction applies to
   writing brand-new pattern content exactly as it does to modifying existing files).
9. **Check `.dv-workflow/command_inventory.csv` for change-impact** before and after
   any generator/schema change that could affect an existing pattern — already
   codified in `command-inventory/SKILL.md`'s "Change-Impact Check."

---

## 6. Relationship to the four existing CORE skills

`branch-mapper`, `interrupt-event-dispatch`, `vip-scenario-branch`, and
`command-inventory` already carry real, substantial generic content — none of them is
thin the way `command-generator` is. What they cover, and why none of them is the
missing piece MEM-53FCE2C191 identified:

| Skill | Covers | Does NOT cover |
|---|---|---|
| `branch-mapper` | The four-layer *taxonomy* (what `block`/`branch_a*`/`branch_fw`/`branch_b*` each mean), N:M mapping records, AMBA shared-resource arbitration policy | How to actually write the `fork`/`join` SystemVerilog inside a new pattern *file* |
| `interrupt-event-dispatch` | `branch_fw`'s internal ARM/WAIT/WAKE/DECODE/CLEAR loop shape, per-port service-loop parallelism, two generic W1C/mask rules | Where `branch_fw`'s launch site sits relative to `block`/`branch_a*`/`branch_b*` in one pattern file, or anything about `branch_b*`'s own composition |
| `vip-scenario-branch` | `branch_b*` as a traceability/record layer (VP_ID → SCENARIO_ID → ... → VIP_SEQUENCE), VIP-sourcing discipline | The concrete `fork`/`join`-not-`join_any` mechanics, or any of the five trap classes in §3 |
| `command-inventory` | Existing `command.txt` as a reusable/backward-compatible capability baseline, change-impact checking | Authoring guidance for a scenario's internal task composition |

All four are real, cited, and should be referenced (not duplicated) by whatever closes
this gap. The gap is specifically: **no skill currently tells an author how to compose
a NEW pattern file's `fork`/`join` structure, which structural rules are load-bearing
(§2, §3) vs. which vary by intent (§4), or what to check before writing one (§5).**
That is exactly what `command-generator/SKILL.md` does not do today, and exactly what
`.claude/skills/CORE/command-generator/SKILL.md`'s existing 23 lines were never meant
to do (its actual job — vPlan-gap-driven `command_mapping.csv` maintenance — is a real,
separate, legitimate job that should not be diluted).

---

## 7. Proposed structure: a new skill, not an expansion of `command-generator`

**Recommendation: add a new skill**, e.g. `.claude/skills/CORE/pattern-architecture/SKILL.md`
(or `command-txt-authoring` — naming is secondary to the argument below), rather than
expanding `command-generator/SKILL.md` in place.

**Why a new skill, not an expansion of the existing one:**
- `command-generator`'s stated job (front matter: "Generates or extends command.txt
  scenarios and command-to-handler/VIP mappings from vPlan gaps while preserving DE
  compatibility") is about *which commands must exist* and *how they map to
  handlers/VIP sequences/coverage* — a planning/traceability job, driven by vPlan gaps,
  producing `command_mapping.csv`. This document's content is a *different* job: given
  that a new pattern file needs to be written, how is its SystemVerilog task
  composition actually structured. Folding both into one file would make an already
  vPlan-facing skill also carry a completely different audience's mechanics
  (concurrency semantics, trap catalogue), which is exactly the kind of overloading
  that makes a skill hard to keep both correct and navigable.
- The four existing CORE skills (§6) are already split by concern (taxonomy vs.
  event-loop internals vs. traceability vs. inventory) rather than merged into one
  mega-skill — a fifth, cleanly-scoped skill (task-composition mechanics) is
  consistent with that existing decomposition, not a break from it.
- `command-generator` should instead **reference** the new skill (one line: "for the
  internal task-composition shape of a pattern file being newly generated, see
  `pattern-architecture`"), the same way `interrupt-event-dispatch` and
  `vip-scenario-branch` already cross-reference `branch-mapper`'s arbitration-policy
  section rather than restating it.

**Proposed section-by-section content for the new skill file** (mirroring this
document's structure, condensed to skill-file density, generic-language throughout,
each generic point carrying exactly one labeled USB illustration as this document
does):

```
---
name: pattern-architecture
description: Defines the block/branch_a*/branch_fw/branch_b* task-composition
  shape a new command.txt/pattern file's SystemVerilog must follow -- fork/join
  semantics, the recurring trap classes, and what varies vs. stays fixed by
  test intent. Complements command-generator (which command IDs must exist)
  with how a generated pattern's internal task composition must be built.
allowed-tools: Read Grep Glob Edit Write PowerShell
---

# Pattern Task-Composition Architecture

## The five-layer shape
  (this doc's §1, condensed: block -> branch_a* -> branch_fw -> fork/join
  branch_b* -> verdict, each layer's role and non-blocking/blocking status)

## join, not join_any -- and when the guarantee expires
  (this doc's §2: the generic statement, the authoring rule "default to join,
  join_any requires written justification that must be revisited whenever the
  fork's composition changes")

## Recurring trap classes (generalize, do not enumerate USB traps as Harness rules)
  3.1 shared-sequencer-lock arbitration between DUT-driven and VIP-driven task
      groups (cross-refs branch-mapper's AMBA M x N section for the
      within-branch-A instance of the same class)
  3.2 stage-ordering dependency must be verified per-port, not globally
  3.3 shared destination variable races once two branches hold independent
      locks
  3.4 configure-before-enable pause point for shared per-port bring-up includes
  3.5 non-blocking dispatch needs its own explicit paired wait
      (narrower instance of the join-not-join_any class, inside a branch body)
  3.6 a single pattern-wide "is this port my subject" gate silently skips a
      divergent port in a mixed-configuration run

## What varies vs. stays fixed by test intent
  (this doc's §4: default one-branch_b-per-port vs. deliberate cross-port
  collapse when ordering itself is the subject, always explicitly labeled;
  shared per-port body include vs. inline bypass when the shared include
  transitively pulls in behavior the new pattern must avoid)

## Pre-flight checklist before writing a new pattern file
  (this doc's §5, as an actionable numbered list)

## Relationship to sibling skills
  (this doc's §6 table, so an agent lands on the right skill for the right
  question instead of re-deriving taxonomy/event-loop/traceability content
  that already exists elsewhere)
```

**What NOT to do:** do not encode this as generation *code* in
`dv_harness/uvm_generator/` (a `pattern_content_generator.py`) as a first step. The
trap classes in §3 are the kind of judgment call ("does this dependency need a
per-port check or a global one," "is this fork's completion-time guarantee still
true") that benefits from an agent reasoning against real per-project evidence each
time, the same way `interrupt-event-dispatch` and `vip-scenario-branch` deliberately
stayed skill-guidance rather than becoming templated codegen for their respective
concerns. A future skill-validated, real, multi-protocol track record (per the
Methodology Consolidation Rule) would be the trigger to promote parts of this into
generator code, not the first step.
