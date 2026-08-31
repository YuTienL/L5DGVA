---
name: ip-uvm-dv-gen
description: Use when working inside a Synopsys VIP-based IP-level UVM verification environment laid out as DUT/ Doc/ Spec/ VIP/ - building it, adding a UVM agent or sequence, wrapping a VIP sequence as a task, converting or auditing a command.txt BFM pattern, hooking into vcs.opt or the BFM model layer, writing the Makefile, filelists or Verdi setup, or producing the vPlan and user guide. Toolchain is VCS and Verdi. Target IP is a parameter: USB, PCIe, Ethernet, MIPI CSI-2, MIPI DSI, CAN-FD, eDP, eMMC, SDIO, AMBA4 or another.
---

# IP-level UVM DV environment -- working reference

The operational companion to the **`IP_UVM_DV_Gen`** agent
(`.claude/agents/IP_UVM_DV_Gen.md`). That agent carries the full
end-to-end process, the reasoning behind each step, and the anti-patterns;
this is what you keep open while doing the work.

**Authority split (set explicitly, 2026-08-29 import/reconciliation pass):**
the agent is authoritative for the process itself; **this skill is
authoritative for the operational quick-reference and the confirmed-drift
log** below -- dated real-project observations of where an actual
environment diverged from the process, and whether that was a defect or a
legitimate evolution. Where a step has real generator code backing it in
`dv_harness/uvm_generator/`, both files point at the same module rather than
restating its schema independently -- currently: `bind_mechanism_generator.py`
(two-hook skeleton + evidence-gated `bind`), `address_map_verifier.py`
(Step 3's three-independent-source address method), and `generator.py`'s
`virtual_sequences`/`SCOREBOARD_CHECKS` DSLs (Steps 7/8). If this skill and
the agent file ever read as contradictory on the same point, that is a bug in
one of them, not an acceptable state -- fix the stale one rather than
picking whichever you read first.

**Use the agent when starting a new environment.** Use this skill when you
are already inside one and need the rule for the thing in front of you.
**`IP_UVM_DV_Gen.html`** is the offline console for the same process --
workspaces, status bar, gates, and a kickoff-brief export.

---

## Fixed toolchain

| Role | Tool | What it forces |
|---|---|---|
| Simulation | **Synopsys VCS** | Two-stage `vlogan` then `vcs`. Filelist paths resolve against the **working directory**. Partition compile rebuilds globally on any command-line change |
| Debug | **Synopsys Verdi** | **FSDB only** -- never VCD or VPD. `-kdb` in **both** stages. `-debug_access`, not `+all`, for post-processing |
| VIP | **Synopsys VC VIP (SVT)** | UVM flow includes the *unparameterised* interface. Needs `-ntb_opts uvm` plus the VIP's `use_sigprop`. Width defines truncate silently if unset |

## Target settings

Set by the user, recorded at the top of the environment's `CLAUDE.md`:

| Setting | Values |
|---|---|
| `TARGET_IP` | `USB` `PCIe` `Ethernet` `MIPI_CSI` `MIPI_DSI` `CAN_FD` `eDP` `eMMC` `SDIO` `AMBA4` or another |
| `IP_PREFIX` | `usb_` `pcie_` `eth_` `csi_` `dsi_` `canfd_` `edp_` `emmc_` `sdio_` `axi_` |
| `DUT_ROLE` | **The VIP takes the opposite role.** Confirm from the RTL |
| `ATTACH_LAYER` | `serial` (pads) or `digital` (controller-to-PHY). A build configuration, not a runtime switch |
| `PORT_VIP_MAP` | For a multi-instance/multi-port target: which real instances get a bound VIP, and whether they share one config or need different ones per port -- **confirm explicitly, don't infer from the port count** (confirmed gap, 2026-08-31: a 2-port USB target's per-port VIP-binding topology was not asked until the human raised it) |

**Standing rule (2026-09-01): the `<ip>`/`IP_PREFIX`/generic-naming
convention applies ONLY to this harness's own reusable template assets
(this file, the agent file, `dv_harness/uvm_generator/templates/`) --
never to what you generate for a real project.** A real deliverable uses
real, concrete names throughout (`usb_seq_launcher.sv`, `USB_GCTL`, real
project signal/instance names) -- never leave literal `<ip>`/`IP_PREFIX`
placeholder text in a real deliverable, and never genericize a real
deliverable's already-concrete names back toward something generic.

**The reverse direction (2026-09-01): when distilling a real pattern from
a sibling project's own protocol-specific files (Iron Rules, a Makefile,
any real-project knowledge) into a permanent harness asset, rewrite it in
protocol-agnostic/generic form** -- do not copy the source's rule text
verbatim with its concrete protocol/signal/task names left in place;
extract the lesson and state it generically. A concrete real-project
example may still be cited as an illustration; the rule's own statement
must be generic.

---

## The tree

```
<project>/
|-- DUT/          READ-ONLY except two guarded hook blocks
|   |-- ENV/ MACRO/           libraries and hard macros
|   |-- MODEL/                BFM model layer      <- HOOK 1 goes here
|   |-- RTLCAT/               RTL, chip top, decoder, parameter header
|   |-- command.txt           the existing test script
|   `-- vcs.opt               DUT filelist         <- HOOK 2 goes here
|-- Doc/          DUT and IP documents: databook, programming guide, register map
|-- Spec/         protocol and interface standards
|-- VIP/          READ-ONLY.  examples/ include/ lib/ src/
|-- uvm/          YOU CREATE.  tb/ filelist/ hex/ docs/ vplan/
`-- sim/          YOU CREATE.  scripts/ is input; everything else is a product
```

| Path variable | Value |
|---|---|
| `DUT_ROOT_PATH` | `<project>/DUT` -- the five directories and `vcs.opt` must be siblings, and here they are |
| `VIP_HOME` | `<project>/VIP` -- must include the protocol VIP **and** the register-bus VIP **and** the DMA-bus VIP |
| `UVM_ROOT_PATH` | `<project>/uvm` |
| `SIM_ROOT_PATH` | `<project>/sim` |

**Confirmed drift (2026-08-28, real project evidence, not hypothetical):** a
live project had `ENV/`, `MACRO/`, `MODEL/`, and `command.txt` as siblings of
`DUT/` at the project root instead of children of it -- the project's own
build system (its Makefile) required the five items to be direct siblings
of each other, and its own maintained notes had already flagged the mismatch
as an open item. A staging/authoring checkout organically drifting away
from this exact assumption has now been observed independently more than
once -- treat it as a real, recurring shape, not an anomaly to route around
silently. If you find this drift: (a) do not "fix" a live project's layout
yourself, that's a decision for whoever owns it; (b) if you are instead
**packaging** a fresh copy of the environment (see `environment-packaging`),
reorganize the copy into the structurally required shape -- it's safe
because it's a new copy, and it produces a package that's actually
self-contained rather than perpetuating a layout that only works because
someone else's build points `DUT_ROOT_PATH` somewhere with the correct
nesting.

### Where to look for what

| Need | Go to |
|---|---|
| IP configuration, role, enabled features | `DUT/RTLCAT/**/*_params.svh` |
| Register base addresses | **The decoder in `DUT/RTLCAT/`.** `Doc/` corroborates, never decides. Cross-checked mechanically (three independent sources: decoder + BFM-access histogram + doc) by `dv_harness/uvm_generator/address_map_verifier.py:verify_address_map` -- see the agent file's Step 3 for the method, that module's docstring for the schema |
| Chip top ports, bus declarations, clock chain | `DUT/RTLCAT/` |
| Where the register macros are defined | `DUT/MODEL/` -- the redirect must precede the model's task definitions |
| Which `ifdef` branches are live | `DUT/vcs.opt` defines |
| The IP initialisation table to audit patterns against | `Doc/` databook |
| Clause numbers for the vPlan | `Spec/` |
| Sequence collections, interfaces, class names | `VIP/src/`, `VIP/include/` |
| DUT wiring templates, closest topology | `VIP/examples/` |
| The DE's actual current compile/run script, by name | Not just `vcs.opt` -- ask for and read the real launcher (e.g. `runver_precomp`/`runver.sh`-style). **Confirmed drift (2026-08-31):** a real project had a second, plausible-looking launcher that silently built the wrong top-level config (an XMR-excluding `-top` override); the correct script's own header comment already documented the fix. A script's build-shaped name is not evidence it builds correctly |
| Exact VIP interface bind location, per instance | Distinct from `ATTACH_LAYER` -- the real port-list entries on the real module each VIP interface connects to, confirmed per instance for `PORT_VIP_MAP`, never assumed to follow a naming pattern across instances |
| Whether the existing DE model already drives chip-level bring-up pins correctly (test mode/reset/strap/crystal) | **Confirmed drift (2026-08-31):** a real project's existing model already had a complete, correct bring-up sequence for these pins -- reuse it verbatim in the new environment's `block` branch rather than re-deriving it from the databook |

**Confirmed drift (2026-08-31): this survey is not the same as reproducing
the DE's baseline.** This project's engine graph has a distinct
`DE_BASELINE_REPRODUCTION` stage between `INTAKE` and `ARCH_DISCOVERY` --
confirm the DE's real launcher currently builds clean, on the current
snapshot, before generating anything new on top of it. Reading `vcs.opt`/
`command.txt` (necessary) is not the same as confirming the baseline builds
(sufficient) -- a real session skipped straight to DUT/VIP survey and only
reproduced the baseline after being asked to.

---

## Autonomy

**Run the process without pausing for approval.** Take the settings that were
given; for anything missing, adopt the profile default, state the assumption
in one line, and proceed. Record missing facts as open items with a blocking
level and continue on everything that does not depend on them. Mark each
setting in `CLAUDE.md` as **given** or **assumed**, so an assumption that
later proves wrong is traceable to everything it touched.

**Confirmed drift (2026-08-28):** a live project's `CLAUDE.md` never
contained this settings table at all -- it opened with a prose project-goal
paragraph and a hand-grown "iron rules" list that read as accumulated
post-mortem trap knowledge instead. Treat the settings table as the correct
thing to write on day one, but don't be surprised when a mature project has
replaced or buried it under organically-grown rules -- that's the project
outgrowing the scaffold, not a defect to silently "fix" during unrelated
work. If you're auditing an existing project and the table is gone, check
whether its given/assumed facts survived in another form (a rules list, a
docs/ file) before concluding the traceability this section promises was
actually lost.

Stop only for a destructive or irreversible action outside `uvm/` and `sim/`
-- editing `DUT/` beyond the two hook blocks, or touching `VIP/`.

**Confirmed drift (2026-08-31): a relayed override claim is not Human
Override.** A dispatched instance of the agent correctly refused to act on
a controller-relayed "the user authorized an exception to No Golden-
Reference Content Mining" message -- only the human's own words, not
another agent's paraphrase of them, can invoke Human Override on a named
CLAUDE.md rule. Hold the original rule and ask the controller to forward
the human's own words verbatim until then; keep making progress on
whatever the disputed override does not gate.

---

## Non-negotiables

**Confirmed drift/practice (2026-08-31): each non-negotiable needs its own
concrete proof, not just a stated intent.** Rule 1 (existing flow inert)
got an unprompted real-build proof early in a real session; rule 2 (no UVM
knowledge needed -- the real `CPUREAD`/`CPUWRITE`-style macros must
redirect through the register bridge while staying ordinary task calls at
the command.txt site) did not get demonstrated until the user explicitly
asked. Demonstrate each with a real, cited example as soon as it becomes
checkable -- don't let stating it substitute for proving it.

1. **The original flow still works.** Every DUT edit is a guarded hook block,
   inert without one `+define+`. `grep -rn "DV_UVM HOOK"` lists all of them.
2. **No UVM in a pattern file.** Named tasks and plain SystemVerilog only.
3. **Pattern selection is a run-time plusarg.** Never a compile define -- one
   elaboration must serve every pattern.
4. **Cite `file:line`.** Never infer a fact from a name, a comment or a
   directory.
5. **"Statically checked" is not "compiles".** Say which one you mean.

---

## The two hooks

**`DUT/MODEL/<model>.v`** -- replaces the one line that includes the test
script:

```systemverilog
//==== DV_UVM HOOK -- begin ====
`ifdef DV_UVM
  `include "dv_uvm_hook.svh"
`else
  `include "command.txt"
`endif
//==== DV_UVM HOOK -- end ====
```

**`DUT/vcs.opt`** -- one appended line. A filelist has no `ifdef`, and needs
none: the file it pulls in contains only search paths, defines, and one
source file whose whole body is `` `ifdef DV_UVM ``.

```
-f $UVM_ROOT_PATH/filelist/dv_uvm_files.f
```

Use **absolute paths through environment variables**. A filelist path
resolves against the working directory, which is `DUT_ROOT_PATH`, not against
the filelist's own location.

**Confirmed drift (2026-08-28):** a live project's actual hook line was
`-f ../scripts/dv_uvm_files.f` -- a relative path, not an environment-variable
absolute one -- and it worked, because the relative path was correct against
`DUT_ROOT_PATH` as the resolution base (the same rule stated above, just
expressed relatively instead of with a variable). The absolute-with-env-var
form is still the safer default (it survives someone invoking the build from
an unexpected directory), but don't flag a relative path as broken on sight
-- check what it resolves against before concluding it violates this rule.

### What must be at top-module scope (cannot be `bind`-ed)

| What | Why |
|---|---|
| The bridge instances | Patterns reach them by hierarchical path |
| **The macro redirect** | Preprocessing is sequential. Placed before the model's task definitions, every register access inside those tasks is redirected with no edit to any of them |
| The pattern `initial` block | Declares the variables patterns use, under the original names |

Everything else uses `bind`, targeted at **where the signals actually are** --
signals declared at chip level with the subsystem merely connecting to them
get bound at chip level.

---

## Bridges

Two worlds that share nothing: the design database (modules, nets, static
tasks, events -- exists before time 0, addressed by hierarchical path,
visible in the waveform) and UVM's run-time objects (created by `run_test()`,
addressed by handle, **invisible to the waveform viewer**).

The only crossing is **static storage with a dynamic value**:

```systemverilog
module <ip>_seq_launcher;
  string req_seq_name, req_target, req_argstr;
  int    req_arg0, req_arg1;
  bit    req_background, req_ok, ready;
  event  req_posted;   // Verilog -> UVM
  event  req_done;     // UVM -> Verilog
  semaphore lock = new(1);
```

Build two: one for register access, one for sequence launching. Keep an
owner/name field in each -- it makes the boundary readable in the waveform,
which is how you tell "Verilog never posted" from "UVM never answered".

**Real-code status:** `bind_mechanism_generator.py` emits the two hooks and
evidence-gated `bind` statements, but accepts this bridge module's own
content (`top_scope_decls`) as an opaque, already-authored string -- it does
not yet generate the `req_seq_name`/`req_posted`/`req_done`/`semaphore lock`
struct from a schema. See the agent file's Step 6 for the same note; not
closed as of the 2026-08-29 pass.

### Physical signal-level connections -- `tran` vs `assign` vs `force`

A separate, lower-level bridge problem from the logical one above: wiring
the VIP's pad-level interface signals to the DUT's actual pads. Confirmed
against a real serial-protocol project (2026-08-28), generalizes to any
protocol whose physical layer has bidirectional or multiply-driven pins
(differential pairs, shared data/clock lines, open-drain buses):

- **If the VIP declares the signal `wor`** (multiply-driven, resolved) **and
  the DUT pad is `inout wire`**, connect with the `tran` primitive, never
  `assign`. `assign` forces a single direction and silently breaks the
  bidirectional/multiply-driven arbitration the real pins depend on --
  it will not error at compile time, only misbehave at runtime once both
  sides try to drive.
- **Where a lane's direction is structurally fixed** (a differential
  TX-only or RX-only lane in a point-to-point serial link), a plain
  `assign` on that one directional lane is correct and simpler than `tran`
  -- don't `tran` a signal that only ever has one driver.
- **Sideband/control pins declared `inout`** (test-mode, reset, trap,
  clock-select and similar) cannot be driven with a bare `assign` of a
  constant either; drive them with a `reg` under real time-sequenced control
  (or `tran` through a pullup/pulldown), matching how the real DUT bench
  expects them to come up.
- **Whether a VIP genuinely replaces an existing proven bus-master task or
  the bridge only wraps it for ordering/visibility is a decision to state,
  not assume.** Confirmed real case (2026-08-31): the safer default (keep
  the proven task as real master) was explicitly overridden by the user in
  favor of real VIP ownership. If replacing: attach the new master at the
  old master's own real top-level port (found in Step 3's survey), not at
  a point deep inside the interconnect near an arbiter.
- **When a VIP/AXI/APB-style bus VIP replaces a bus master via `force`**
  (rather than a real port connection), **force only that master's
  OUTPUTS** (address/data/valid/write-enable signals) onto the target bus.
  **Never force the master's INPUTS** (ready/response/error signals) --
  those must stay driven by the real slave logic and only be *observed* by
  the VIP; forcing them breaks the handshake the slave is genuinely
  driving, and the DUT will wait forever for a ready/response that a force
  is now silently supplying a fixed value for instead of the real logic.

### Termination -- silent failures live here

> **A `run_phase` with no objection does not wait. It ends at time 0 and
> reports a pass.**

- A pattern in a Verilog `initial` cannot raise an objection. Give it a
  module-scope `pattern_done` bit; the base test objects at time 0 and waits
  on it. **Forgetting to set it = instant pass.**
- Forking a sequence and returning without joining = same silent pass.
- **Both bridges need their own timeout layers, not just the sequence
  launcher.** Confirmed real gap (2026-08-31): a register bridge with no
  timeout turned a real hang into a dead simulation with zero diagnostic,
  instead of a message naming the stalled address.
- Three timeout layers, each naming what it waited for: per-request (fatal,
  names the sequence) -> per-group join (bounded, **lists what has not
  returned**) -> whole-pattern (error, epilogue, forced finish).
- **The forced finish goes in `final_phase`, not `run_phase`** -- otherwise
  the regression's result line never prints and a hang becomes "no verdict".
- Time-0 ordering between the pattern's first access and `run_test()` is
  undefined. The bridge **waits**; it does not check-and-fail.

**Standing rule (2026-09-01, distilled/genericized): never `disable
fork`/named `disable` across instances sharing one lock.** A bounded
`fork ... join_any` inside a per-instance branch must save each spawned
branch's `process::self()` handle and, after `join_any`, `.kill()` only
the handles this fork itself produced -- never a bare `disable fork;` or
a named `disable <label>;` when multiple instances share one
capacity-limited resource lock. Failure mode: not a clean timeout, but a
silent, total, permanent hang of every future access to that shared
resource, because `disable fork` kills the calling process's whole
descendant subtree -- which can reach a sibling instance mid-dispatch and
holding the lock. A named-label variant is worse: two instances can share
an identical label, letting one's disable kill the other's still-running
block. Real worked example (USB, DWC_usb31 wrapper): a sibling project
hit both forms (label collision between two ports' bring-up forks; a bare
`disable fork` in one port's IRQ-service wake killing the other port's
in-flight dispatch) and fixed every bounded-wait site with the
`process::self()`/`.kill()`/`join_any` idiom above.

**Standing rule (2026-09-01, distilled/genericized): never `$finish` --
always end via a name-matched final-check call.** `$finish` skips
whatever end-of-test hook prints the pass/fail line regression tooling
parses. End every pattern via a project-defined final-check macro/task
taking the pattern's own registered name, checked to match. For a
multi-instance/multi-config pattern with per-instance applicability, use
a shared run counter incremented only when an instance actually exercised
applicable content, checked non-zero after join, with an explicit error
if nothing applicable ran anywhere (must not read as the same clean pass
as a real run). Real worked example: a sibling project's `FINAL_CHECK("<
name>")` macro plus a shared `..._ports_run` counter with an explicit
`ERROR: <name> exercised no port` message.

### Concurrency

A capacity-1 semaphore held until the response event means **blocking
wrappers can never overlap**, however the pattern is written -- `fork ... join`
of three blocking tasks is sequential, in an unpredictable order. Real
concurrency needs a separate non-blocking launch path plus an explicit join.

**Never run register access concurrently with the bus VIP's random traffic**
if both servers sit on the same sequencer: separate locks means they really
do overlap, one sequencer means UVM interleaves them, and random-address
writes land in the IP's register space with no error message at all.

**Standing rule (2026-09-01, distilled/genericized): `join`, never
`join_any`, on the outer per-instance host-script fork once a background
service branch is independently forked.** Once `branch_fw`'s per-instance
loops run independently, bring-up branches finish long before either host
script -- `join_any` on the outer fork ends the whole pattern on the
first (typically a bring-up branch, microseconds in) to return: 0 errors,
looks like a clean pass, tested nothing. Close with a plain `join`.
Patterns that legitimately need single coordinated closure across
instances declare the deviation with an explicit project-chosen tag
comment (a sibling project uses `//SIX-BRANCH-EXC: <reason>`); a static
checker should hard-FAIL an undeclared deviation and flag a
declared-but-unused exception too (it can silently hide the next real
violation).

**A reusable multi-instance pattern architecture** (observed in a real
multi-port project, 2026-08-28 -- consider for any target with >=2
independent instances/ports, not USB-specific): one blocking "Global"
section for once-only SoC bring-up (clock/PLL/reset), then per-instance
controller/register bring-up branches (`branch_a<n>`) forked `join_none` so
they run in parallel, then ONE `branch_fw` CALL SITE forked `join_none`
that itself forks **one independent per-instance service-loop process per
instance** (not a single loop that internally iterates over every
instance -- see "Correction (2026-09-01)" below), and finally per-instance
VIP-driven host-script branches (`branch_b<n>`) that the pattern itself
`fork`s and `join`s (these are what actually gate the pattern's
completion). The load-bearing distinction to preserve if you adopt this
shape: the per-instance bring-up branches and `branch_fw`'s own
per-instance service-loop processes are NOT the same thing and must not
be collapsed into one -- a background service loop that happens to serve
multiple instances is not itself "the parallel per-instance work"; that
work is the separate bring-up branches running alongside it.

**Correction (2026-09-01, distilled from a real sibling project, matching
the correction now in `IP_UVM_DV_Gen.md`):** this section previously
described `branch_fw` as one shared loop internally servicing every
instance -- wrong, and inconsistent with `interrupt-event-dispatch/
SKILL.md`'s FW Service Loop section, which already had the correct
per-instance-process shape. A single shared scheduler looping over
instances in one process is a real, previously-tried, measured-worse
alternative (a real cross-instance interrupt-service stall of several
microseconds was measured when this was tried) -- do not regress to it.

**Standing rule (2026-09-01, distilled/genericized): cross-branch
synchronization needs one one-way barrier flag per synchronization
point.** The branch kinds above aren't synchronized just by running in
parallel -- declare a set-once, never-cleared module-scope flag for
`block`'s completion, one per `branch_a<n>` instance's completion, and
one per `branch_fw` instance's own one-time-setup completion. A
`branch_b<n>` depending on more than one predecessor must wait on the AND
of every relevant flag (never just one) and report which specific flag is
missing on timeout, not one generic message. Real worked example (USB,
DWC_usb31 wrapper): a sibling project's three such flags, ANDed in its
host-script wait task with two distinct timeout messages -- this mattered
because a fast controller bring-up could raise its own flag before that
port's firmware instance finished setup, leaving a real window with
nothing yet programmed to answer host-side traffic.

---

## Wrapping VIP sequences

| Idiom | Randomizes | Consequence |
|---|---|---|
| `uvm_do` | **yes**, every unpinned `rand` field | Byte enables, protection attributes and lengths become random unless pinned |
| `uvm_create` + `uvm_send` | **no** | Every field keeps its declared default -- and a wrong default is wrong *every* time |

- **VIP constraints are often conditional on "that feature is disabled".**
  Enabling a feature means owning all of its fields.
- **Read the declaration; never guess arity from the name.**
- **Response handshakes are mandatory** where defined -- read data is often
  only valid after one, and skipping it overflows a response queue.
- **Do not over-constrain the protocol path**; many VIPs derive direction and
  addressing from configuration, and an extra constraint makes randomize fail.
- **Configuration arrays are indexed by position**, not by the protocol's own
  numbering.
- **Compile-time width defines have narrow defaults** -- set data width,
  address-user width and similar explicitly or they silently truncate.
- Vendors ship **misspelled class names**; copy them verbatim.

---

## Converting a BFM pattern

```
Keep verbatim : every access that programs THE DUT
Delete        : everything that programs the far side the VIP replaces
Add           : a few VIP task calls in its place
```

**Standing rule (2026-09-01, distilled/genericized): preserve a deleted
line as a tagged comment, never a silent deletion.** Keep a no-longer-run
converted line as a comment tagged with one of three categories:
already-dead-in-the-original (a record, not something this conversion
skipped), superseded-by-a-live-line (state where), or
host-side-original-now-performed-by-the-VIP (permanently uncompilable,
never uncomment). A tag, once applied, is never removed. An untagged
commented-out call to a known reference-API function is a defect a
static checker should catch.

**Standing rule (2026-09-01, distilled/genericized): pattern file
sectioning convention.** Every pattern opens with a provenance banner
(what it's ported from, pointer to the framework doc). A simply-ported
pattern uses SETUP / TEST CONTENT / VERDICT section banners, with a
"no counterpart in the original" marker on any newly-added section. A
multi-branch pattern instead banners each fork branch by role and uses
inline numbered sub-labels within a branch so each original scenario step
has a traceable landing spot.

Then **prove equivalence**: resolve address macros to literals, compare
register writes one-for-one against the original, and classify every
difference.

**Confirmed drift (2026-08-31): a proven task's real behavior is bigger
than its headline protocol function.** Before replacing one, enumerate ALL
of it -- a real session named a reset-gate wait, conflict detection,
byte-strobe generation, clock-relative timing, and existing logging as
candidates for the same silent right-transaction-wrong-data bug class a
byte-shift/lane-extraction question started from. Read every real
behavior, not only the transaction performed, before claiming equivalence.
Following through on this, a real audit of three register-access widths
found NO uniform shift rule -- the narrowest width shifted fully on both
low address bits, the middle width used only one bit (silently serving a
misaligned access as the aligned one below it), and the full-word width
ignored alignment entirely. **Replicate quirks (including silent
misalignment handling) exactly -- do not "fix" them**; equivalence is the
requirement, a correctness improvement is a separate, opt-in decision that
can silently change behavior for an existing pattern relying on the old
shape.

**Confirmed drift (2026-08-29):** this abstract equivalence-proving method
has a concrete, real implementation shape worth using as the target for a
future generalized static-check layer — a real sibling project's
`sim/scripts/check/reg_audit.py` (103 lines) scans every pattern file for
named register-write calls (e.g. `` `CPUWRITE4B(`USB_GCTL/GUCTL/..., ...) ``),
decodes named bit-fields, checks them against measured/derived required
values, and reports results in an `inspected`/`DISAGREEMENT` vocabulary
(run as `python3 reg_audit.py <tbdir> | grep -E 'inspected|DISAGREEMENT'`).
Treat this as real worked-example prior art, not something to design from
scratch, if/when this static-check concept is generalized beyond one
project.

Then **audit against the databook initialisation table in `Doc/`**. Expect:

- a required step missing from nearly every pattern
- steps in an order that matters, reversed
- **enable masks that do not cover what was configured** -- compute the mask
  from the configuration commands the file actually issues
- a per-transfer resource armed once per pattern instead of per transfer
- the IP's soft reset confused with the SoC wrapper's reset
- hard-coded absolute paths into someone's home directory (a failed memory
  load usually only *warns*, so the buffer is zeros and nothing happens)

None of these fail compilation. The symptom is always a far-side timeout.

---

## Checkers and scoreboard

> **Confirmed drift (2026-08-31): ask the user's checking priorities before
> Step-8-equivalent design work, not during it.** A real session reached
> this point without asking whether VIP built-in checkers alone were
> sufficient, whether end-to-end payload comparison was required, or whether
> the user had a specific named requirement (real example: an AXI DMA master
> port from the DUT to system memory needed an explicit `<ip>_dma_scoreboard`
> with a **passive-monitor-only** connection, since the DUT itself drives
> that bus during DMA -- see "Keep 'our stimulus'..." below, this is the
> textbook case it describes).

- **Count the VIP's built-in checkers first.** Moving from BFM scripts (which
  usually check nothing) to a VIP is the largest single increase in checking
  the project gets.
- Per-check coverage switches usually default **on for failures, off for
  passes**. Turn the pass side on to answer "was this ever exercised".
- **Find the real observation point.** Some agents publish on an analysis
  port; some publish nothing and a protocol callback is the only hook. Check
  the agent's ports before designing the connection.
  **Confirmed drift (2026-08-29):** a real, concrete instance of this rule --
  a sibling project's real debug sessions read the VIP monitor's plain-text
  `transaction_trace` file directly (e.g.
  `env.apb_env.master.monitor.transaction_trace`,
  `env.apb_env.slave_0.monitor.transaction_trace`) with `wc -l`/`tail`/
  `grep -c <addr>` to answer "did this register write actually reach the
  bus", with no Verdi/FSDB session needed at all. Check whether the current
  VIP exposes an equivalent plain-text trace file before reaching for a
  waveform tool.
- **Check the right response field** -- a scalar initialised to OK and
  meaningful only for writes will pass every read error silently.
- **Footprint is not payload.** `beats * bytes_per_beat` overstates a partial
  final beat. Use the VIP's byte count or count asserted byte enables.
- **Prefer invariants to reconstruction.** Do not compare beat-by-beat when
  the DUT may legally split, reorder or relocate. **A scoreboard that
  false-alarms gets switched off, and then it checks nothing.**
- **Know when your observation fires** -- a protocol callback fires when the
  protocol layer *sees* the transfer, not when data movement completes.
- **Keep "our stimulus" and "the DUT's own traffic" in separate envs.** An
  error on one means the testbench is wrong; on the other, the design is.
- **`$realtime` is in the enclosing scope's timeunit.** Write
  `$realtime / real'(1s)` so the ratio is seconds in any timescale.

---

## Build system

> **Standing rule (2026-09-01, explicit Human Override, permanent, updated
> 2026-09-01 to record internalization): `sim/scripts/` build
> infrastructure is based on a template now internalized at
> `dv_harness/uvm_generator/templates/sim_scripts/`** -- originally copied
> byte-identical from `D:\DV\Task\USB_UVM_Handoff\sim\scripts\` after
> explicit, repeated user authorization, and now a permanent harness asset
> in its own right. **The external path no longer needs to be read for
> this purpose**, and note it is **no longer byte-identical** as of a
> 2026-09-01 genericization pass (real `TARGET_IP`/`IP_PREFIX`
> parameterization, verified working by re-importing `pattern_rules.py`
> with `TARGET_IP=PCIE`; DUT-internal RTL/silicon facts in `waves.tcl`/
> `reg_audit.py` kept as explicitly-labelled worked examples, not
> mechanically substituted -- see `.work/genericize-sim-scripts-report.md`,
> session-local). Internalized set: `Makefile` (canonical build entry
> point), `waves.tcl`, `lsf_regress.sh`/`lsf_run.sh`/`lsf_wait.sh`,
> `ip_run.sh` (renamed from the source's `usbrun.sh` -- not invoked by
> literal filename in the Makefile, confirmed safe to rename, kept
> `<ip>`-generic like every other file in this manifest),
> `gen_pattern_pool.py`, and `check/`'s eleven-category static self-check
> family (`include_order.py`, `macro_selfcontained.py`, `make_order.py`,
> `pattern_rules.py`, `reg_audit.py` -- the same equivalence-proving tool
> already cited under "Converting a BFM pattern" above, `vip_guards.py`,
> `vip_members.py`, `zero_delay_loops.py`). Scope unchanged: build/
> infrastructure mechanics only -- does NOT extend to any other file in
> the reference tree and does NOT authorize protocol-behavior content
> (sequences, scoreboard/checker logic, coverage, vPlan, command.txt
> content) from it. Adapt paths/queue names/resource requests per project
> -- only the template's shape is canonical, not its literal strings from
> the USB session that produced it. **A real trap it documents:** `bsub
> -K` ties a job to its submitting shell and reaps it (`TERM_OWNER`) the
> moment that shell dies -- catastrophic over a transport with
> per-command timeouts (e.g. a telnet/relay bridge) where the submitting
> shell can legitimately die while the job stays healthy. Use plain
> `bsub` (detached) and poll `bjobs` separately whenever the submission
> channel might not outlive the job.

**First-Failure Waveform Rerun -- concrete recipe (2026-09-01), using the
already-internalized template's own knob names:** `make debug
PATTERN=<p> WAVE=1 FSDB_START=<t0> FSDB_STOP=<t1> TOTAL_RUNTIME=<bound>
RUNTAG=<tag>`. `WAVE=0|1|full` selects dump scope (confirm with the user
per the Waveform Dump User Gate; prefer `1` over `full`).
`FSDB_START`/`FSDB_STOP` bound the dump window instead of dumping from
time zero. `TOTAL_RUNTIME` bounds simulated time so the rerun stops near
the first failure. `RUNTAG` avoids overwriting the original WAVE=0
failing run's artifacts.

**Tracked-passing-suite list (regression.list / RECORD=1), 2026-09-01,
distilled/genericized:** already implemented by the internalized
template. Two modes: per-pattern record (`RECORD=1` on a single `make
sim`, gated OFF inside a parallel regression batch to avoid a
multi-host write race) and whole-suite record (`make regress RECORD=1`,
run once after all jobs finish). Both strip any existing line for that
pattern, re-append only on a real pass, then atomically replace the file
-- a FAIL always evicts a stale PASS. Unregistering a pattern cascades
into removing it from this list too. Authoring convention: record the
honest current state (named FAIL reasons), not an aspirational
always-growing list.

**Two-tier LSF integration is site-specific -- verify before reusing,
2026-09-01, distilled/genericized:** before wiring a site's
`vcs`/`vlogan`/`verdi`/`urg`-equivalent tools through the template's
wrapper-flag path, confirm whether those binaries are themselves
site-authored LSF-aware wrappers (use their own flag vocabulary directly,
never nest the project's own `bsub` around them) or plain unwrapped
binaries (route them through the project's own `bsub` path instead, same
mode selection already used for the simulator binary). Carrying one
shape's flag vocabulary to the other silently fails or breaks the
invocation.

- Two stages, both given the debug-database flag if a viewer will be used.
- Consolidate the VIP examples' flags; cross-check against the tool manuals.
- **Compute the timescale constraint** from the configured line rates and
  `$(error)` on a mismatch:
  `required clock = line_rate * oversample`, `half period = 1/(2*clock)`.
  Computing the required resolution is not the same as knowing it will
  actually simulate correctly: confirmed case (2026-08-28) where the
  computed half-period for the fastest supported line rate came out at
  12.5ps, but whether the DUT's own encrypted/vendor hard-macro models
  (PLL, ADC, or similarly protected `.v.e`/`.vp` deliverables) accept a
  timescale that fine was an open, unverified question, not something
  derivable from the spec math -- flag it as a to-be-measured item rather
  than assuming the arithmetic answer is automatically simulatable, and
  don't commit the finest theoretical timescale to the Makefile until that's
  actually been tried.
- **One filelist owns the source list.** Every other filelist carries only
  include paths and defines. A file in two lists is a duplicate-module error.
- Partition compile treats **any** command-line change as a global rebuild.
  Mark which variables force one in the help text.
- Ship a **waveform signal-setup file grouped by the question being asked**
  (did the pattern reach UVM? did the write reach the bus? did the link come
  up?), not by hierarchy. Tolerate undumped signals: list them with the
  remedy rather than failing.

---

## Static self-check (no compiler available)

Run after every change to the testbench tree. In value order:

1. **Call argument count against the declaration** -- by far the most
   valuable. This error lives at the call site, each of which looks right
   alone.
2. Macro invocation arity against the `` `define `` parameter list
3. Block and delimiter balance
4. Undefined macros, and same-name-different-body macros
5. Duplicate task/function/class/module names
6. Format specifiers against argument count
7. Orphan files unreachable from the entry points
8. Pattern pool consistency: include, dispatch and definition agree
9. Duplicate labels in one `case`
10. `extern` with no definition
11. Config-DB set/get key and type agreement

> **The checker produces false positives. Fix the checker before drawing a
> conclusion.** Known classes: mutually exclusive `ifdef`/`else` branches read
> as duplicates; commas inside string literals read as argument separators;
> macros compared against tasks across namespaces; keys built at run time with
> a format function, which no static scan can see.

---

## What the environment must contain

Same shape for every target, with `IP_PREFIX` substituted throughout.
Reproduce the shape even where a protocol has no equivalent of a file --
omitting it is a decision to record, not a default.

```
uvm/tb/top/       dv_uvm_all.sv          one compile entry, body `ifdef DV_UVM
                  dv_uvm_hook.svh        included INTO the TB top; exports task macros
                  <ip>_uvm_bind.sv       VIP interfaces, clocks, run_test()
                  <ip>_uvm_bind_inst.sv  every bind, in ONE file
                  <ip>_reg_arb.sv        register bridge
                  <ip>_seq_launcher.sv   sequence bridge
                  <ip>_dev_init.svh      the databook init table, as macros
                  <ip>_stages.svh        named bring-up stages
                  <ip>_mem_util.svh      descriptor/buffer fill, dump, compare
                  *_vip_tasks.svh        wrapped VIP sequences, one file per protocol
uvm/tb/env/       <ip>_top_env.sv / _top_cfg.sv / _reg_defs.svh / _hier_defs.svh
                  <ip>_probe_if.sv       bind + interface for forced buses
                  <ip>_<x>_check.sv      configuration-consistency checker
                  <ip>_dma_mon.sv        HDL module bound into the subsystem
                  <ip>_dma_scoreboard.sv / _perf_monitor.sv / _payload_publish_cb.sv
                  <ip>_event_bridge.sv / _virtual_sequencer.sv
uvm/tb/seq/       sequences, dispatchers, virtual sequences
uvm/tb/agents/    clock/reset, sideband, register checker
uvm/tb/tests/     ONE uvm_test -- variation comes from patterns
uvm/tb/patterns/  README.md, dv_uvm_pattern_pool.svh (the +PATTERN dispatcher),
                  basic .txt, sanity/ (converted BFM), <protocol>/ (VIP derived)
                  -- this two/three-way split is the DAY-ONE starting shape, not
                  the final one. Confirmed drift (2026-08-28): a live project
                  migrated basic/sanity/<protocol> into ~10 functional category
                  directories (enumeration/link/power/transfer/performance/...)
                  as the pattern count grew, and its own build system tracks the
                  migration in a comment rather than hiding it. Expect and allow
                  this category taxonomy to grow past the initial split; don't
                  treat a richer taxonomy as a deviation to correct back.

                  Standing rule (2026-09-01, distilled/genericized): a pattern
                  .txt may be authored as a BARE BODY (generator wraps it in a
                  named task automatically) or SELF-CONTAINED (it already
                  declares its own named task -- generator emits a bare
                  include instead); detection is by literal presence of the
                  task-declaration string. A helper must produce one shape
                  consistently; the two must never disagree within one file.
                  The dispatcher must report an unrecognized +PATTERN= name
                  explicitly, never silently fall back to a default -- a typo
                  must never be recorded as a pass for a pattern that never ran.
uvm/filelist/     dv_uvm_files.f  SOLE owner of the source list
                  <ip>.f          +incdir+ / +define+ only
uvm/hex/          stimulus and descriptor images
uvm/docs/         README.md, dut-request.md, <ip>-uvm-port-analysis.md,
                  bfm-pattern-analysis.md, command-txt-uvm-migration.md,
                  model-task-uvm-usability.md, uvm-reuse-map.md,
                  <ip>-example-pattern-pool.md, checker-and-monitor-plan.md,
                  <IP>_Verification_User_Guide.pdf + .html
uvm/vplan/        README.md, <IP>_Verification_Plan.xlsx
sim/scripts/      Makefile, waves.tcl
<root>/           CLAUDE.md, README_PACKAGE.md,
                  agents/IP_UVM_DV_Gen.md, reference/bfm_patterns/
                  -- confirmed drift (2026-08-28): a live project shipped the
                  process agent at .claude/agents/IP_UVM_DV_Gen.md instead (where
                  Claude Code actually discovers agents) and never created a
                  reference/ directory at all -- the untouched BFM originals
                  (command.txt + a flat patterns/ of legacy .txt files) sat at
                  <root> directly instead. Both are sensible, literal deviations
                  from this manifest, not defects -- prefer .claude/agents/ for
                  the process agent going forward, and treat an unwrapped
                  original-patterns directory at <root> as an acceptable
                  equivalent to reference/bfm_patterns/, not a missing deliverable.
```

---

## The User Guide

One self-contained HTML file (no external assets), rendered to PDF.
**Fourteen sections, in reading order:**

```
 1 Environment Overview            8 How to Create a Testing command.txt
 2 Architecture                    9 Scoreboard
 3 Directory Structure and Files  10 Checkers
 4 Changes to the Delivered Files 11 Performance Monitor
 5 Verification Work Flow         12 First suite  (converted BFM)
 6 How to Run a Pattern           13 Second suite (VIP derived)
 7 How to Enable Coverage         14 Verification Plan
```

- **Section 4 is the one to hand to the RTL owner**: each edit shown against
  its original content, why it cannot be avoided, what is *not* modified, and
  how to revert.
- **Real vector diagrams, inline SVG. No ASCII art.**
- **A status banner on the contents page** stating plainly what has and has
  not been compiled.
- **Regenerate the table of contents by measuring the rendered PDF, and
  re-measure until the numbers stop moving.** Adding a section changes the
  contents page height, which shifts every page after it -- one pass is
  always wrong.

---

## The vPlan

One `.xlsx`, **generated by a script, never hand-edited**, four sheets:

| Sheet | Contents |
|---|---|
| Verification Plan | One row per item, lettered sections by feature area, auto-filter on, panes frozen at the pattern/task columns |
| Coverage summary | Counts per state, then **the gaps ranked in the order worth closing** |
| Speed / mode matrix | The per-instance configuration grid with the command for each cell |
| Reference | How to run an item, what each suite means, line rates, register bases |

```
ID | Feature area | Verification item |
testing pattern name | command.txt task name | suite | covered by |
testing pattern description | spec section | constraint items |
random or directed | speed | instance | checkers active | notes
```

- **`covered by`** colour coded: covered / `PARTIAL` / `NOT COVERED` / `N/A` /
  `DEFERRED`.
- **`spec section` cites `Spec/` by clause.** No specification available? Say
  so in the sheet rather than filling it with chapter guesses.
- **Validate before writing**: pattern file exists, task is a real
  declaration, pattern is in the dispatcher. Refuse to write on a mismatch.
- **Keep the NOT COVERED rows**, and mark which are blocked on information
  rather than effort. A plan listing only what already runs is a report.

---

## Packaging

A script that wipes and rebuilds from scratch, and **refuses to write the
archive if verification fails**: no undecodable bytes, no unexpected
character sets, line endings normalised, build-file conditionals balanced.
Ship the process agent inside the package.

**Concrete classification rules** (what actually goes in the archive vs
stays behind -- RUN_NEEDED vs dev-scratch, deliverable docs vs process
records, vendor-licensed content, structural-layout fixes, regenerating the
User Guide/vPlan from current state, writing the install README) now live
in `environment-packaging` -- use that skill when actually building a
package rather than re-deriving these rules from this paragraph each time.

---

## Protocol profiles

| `TARGET_IP` | Typical DUT role | Attach at | Where the schedule goes |
|---|---|---|---|
| **USB** | device or host | PIPE/UTMI, or the differential pairs | Enumeration, then link training; descriptors per transfer |
| **PCIe** | endpoint or root complex | **PIPE** above Gen3; serial is very expensive | **Link training (LTSSM)**; TLP/DLLP/PHY means three observation levels |
| **Ethernet** | MAC, sometimes PHY | **xMII** (GMII/RGMII/XGMII/USXGMII) | Descriptor rings; pause/flow control and timestamping are separate axes |
| **MIPI_CSI** | almost always receiver | **PPI** unless the D-PHY model is proven | Frame and line structure -- checks are image-level; virtual channels multiply the stream count |
| **MIPI_DSI** | usually transmitter/host | **PPI** | Command mode and video mode are two separate plans; bus turnaround is the hard timing item |
| **CAN_FD** | node | **the pin pair, always** -- the bit rate makes it cheap | Arbitration and fault confinement, not payload; bit-rate switching is the FD axis |
| **eDP** | source or sink | main-link lanes + AUX | **Link training over AUX**, then video timing and stream attributes |
| **eMMC** | host controller | `CMD`/`DAT`/`CLK` bus pins | Device init and bus-width negotiation, then high-speed mode tuning |
| **SDIO** | host controller | `CMD`/`DAT`/`CLK` bus pins | Card init and function abstraction; interrupt handling is the subtle part |
| **AMBA4** | master or slave per port | **the bus is the interface** | Ordering, outstanding, exclusives, boundary rules. No attachment decision at all |

For a target not listed, fill the same four columns from the IP databook
before starting.

**Confirmed drift (2026-08-31): an existing `` `ifdef ``/`` `ifndef DV_UVM ``
guard around a delivered BFM's drive/force block is itself real evidence of
the delivery's intended architecture.** A session's reasoned "safer
default" (keep a proven bus-master task live) turned out to be broken by
construction -- the delivery already severed that master under `DV_UVM` --
provable only by reading that guard and, further, by actually running the
smallest real test: the smoke run hung (a downstream `pready` never
asserted), which no static argument would have surfaced. When an
architecture choice is questioned, look for this class of guard and run
the smallest real falsifying test where one exists.

**Confirmed drift (2026-08-31): "disable the whole PHY instance" for a
digital/PIPE-style attachment is not automatically correct.** A real
session did exactly that for a PIPE4 USB3 attachment and was directly
corrected by the user -- the PHY was still genuinely in the real data
path; PIPE/UTMI/ULPI is often the PHY's own digital-side boundary, not a
wire bundle floating entirely outside it. Confirm from real RTL/databook
evidence which sub-block (if any) to actually bypass before disabling
anything, and if the DUT has more than one speed-mode PHY (e.g. USB2 and
USB3), confirm whether they are one shared model or genuinely separate
ones first (confirmed separate in this case) -- see the main agent file's
Step 5 for the full three-part verification method.

---

## Bring-up order (do not skip ahead)

```
1  one pattern touching only known-good addresses, no protocol   <- prove the chain
2  single instance, slowest speed, connection only
3  one transfer each direction
4  multiple instances, sequentially
5  multiple instances, concurrently
6  mixed-bus concurrency
7  performance
```

Skipping ahead makes a failure ambiguous between the new feature and a base
path that never worked.
