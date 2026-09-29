# command.txt / Pattern-Architecture Skill Expansion — Implementation Report

Closes the gap confirmed in `MEM-53FCE2C191` and investigated in
`.work/gap-close-command-txt-investigation.md`: the `block`/`branch_a*`/`branch_fw`/
`branch_b*` task-composition architecture used by every real USB pattern file had never
been distilled into a reusable, generic Harness skill.

## What was written, and where

**New skill: `.claude/skills/CORE/pattern-architecture/SKILL.md`** (377 lines, kebab-case
name, frontmatter unchanged in shape from every sibling CORE skill: `name` /
`description` / `allowed-tools: Read Grep Glob Edit Write PowerShell`). This is the
"new skill, not an expansion of `command-generator`" structure the investigation
recommended in its §7, using the investigation's own proposed section-by-section outline
almost verbatim, condensed to skill-file density:

1. **The five-layer shape** — `block` (blocking, one-shot, chip/SoC-global) →
   `branch_a*` (per-port DUT+PHY bring-up, non-blocking, launched from one shared
   include) → `branch_fw` (per-port service loop, non-blocking, launched once, never
   returns) → `fork`/`join` of `branch_b*` (per-port VIP-driven test body,
   port-enable-guarded) → verdict, only after every `branch_b` has genuinely completed.
   Each layer's generic description is followed by one labeled "USB illustration" box
   citing real `USB_UVM_Handoff` file:line evidence.
2. **`join`, not `join_any` — and why the guarantee expires** — the generic concurrency
   statement, the job-98520 USB incident as the illustration of "correct for a while,
   then silently wrong once the architecture evolves," and the authoring rule that a
   `join_any` justification expires the moment the fork's branch composition changes.
3. **Six recurring trap classes**, each stated as a generic CLASS first, illustrated
   second: (3.1) two independent task groups holding conflicting locks on a shared bus
   sequencer, (3.2) a stage-ordering dependency verified globally instead of per-port,
   (3.3) a shared destination variable turning concurrent reads into a silent race,
   (3.4) enabling a resource before it is configured, (3.5) a forked background
   sequence with no paired explicit join, (3.6) a single pattern-wide "is this port my
   subject" gate silently skipping a divergent port.
4. **What varies vs. stays fixed by test intent** — the four-layer ordering,
   `join`-not-`join_any`, and per-branch port-enable guarding stay fixed; whether
   `branch_b*` is split per port, what lives inside each `branch_b*`, whether a shared
   per-port body file is reused or deliberately bypassed, and extra pause-point defines
   all vary, each illustrated with a real USB pattern file.
5. **Nine-item pre-flight checklist** an author works through before writing a new
   pattern file, cross-referencing `branch-mapper`, `vip-scenario-branch`,
   `interrupt-event-dispatch`, and `command-inventory` by name rather than restating
   their content.
6. **Relationship-to-sibling-skills table**, plus a closing note making explicit that
   every USB name/macro in the file is a labeled illustration of a generic point stated
   first in protocol-neutral language, never Harness vocabulary, and that a new
   protocol must derive its own macro/register names from its own VIP/RTL evidence.

**Updated: `.claude/skills/CORE/command-generator/SKILL.md`** — frontmatter left
byte-for-byte unchanged (no stated reason to touch it: its job, "which command IDs must
exist," is real and distinct from the new skill's job). Added one paragraph at the end
of the body cross-referencing `pattern-architecture` by name, mirroring how
`interrupt-event-dispatch` and `vip-scenario-branch` already cross-reference
`branch-mapper` rather than duplicating its content. This resolves the task's "don't
leave two skills silently duplicating the same guidance" requirement: the split is
kept (narrower `command-generator` job is legitimate and pre-existing, per the
investigation's §7 reasoning), connected by a two-way pointer instead of a merge.

**Updated: `CLAUDE.md`** — the "Consolidation status" paragraph under
"Architecture-conformance audit" previously said this gap "remains open." Rewrote it to
record the closure, name the new skill file, and note that `command-generator` now
cross-references it instead of duplicating it — so a future audit reads the current
state directly from CLAUDE.md rather than re-discovering the same gap.

**Synced to deliverable trees** — per CLAUDE.md's Methodology Consolidation Rule
("sync `.claude` to the `industrial` and `PACKAGE` deliverable trees"), copied the new
`pattern-architecture/SKILL.md` and the updated `command-generator/SKILL.md` into
`D:\DV\Task\DV_Agent_Harness_L5\industrial\.claude\skills\CORE\` and
`D:\DV\Task\DV_Agent_Harness_L5\PACKAGE\.claude\skills\CORE\`, verified byte-identical
afterward. Scope note: those two trees already carry substantial, unrelated drift from
`v50` (e.g. `branch-mapper`, `dv-workflow`, `iron-rules`, `make-pattern-api`,
`ip-uvm-dv-gen` all already differed, and `CLAUDE.md` itself differs by ~140 lines,
before this task touched anything) — that pre-existing drift is out of this task's
scope and was left alone; only the two files this task actually changed were synced.

## Verification against USB source before writing (not just re-transcribing the investigation)

Read `enumeration/usb20_enumeration.txt`, `common/soc_run.svh`, and `common/soc_int.svh`
directly (not just the investigation's quotes) before citing them, to confirm the
investigation's file:line citations are accurate rather than propagating a possible
citation drift into a now-permanent skill file. All checked citations matched, with one
correction: the investigation's job-98491 narrative said "258 ms" behind port 1's serial
bring-up; the source comment's own timestamps (`common/soc_run.svh:99-104`, 236739 ns /
255839 ns / 494854 ns) put that gap at roughly 258 **microseconds**, not milliseconds.
The skill file uses the corrected unit ("roughly 258 us").

## Genericity discipline applied

Per the hard constraint and CLAUDE.md's "No Golden-Reference Content Mining" rule
extended to documentation authoring: every rule in the new skill is stated as a generic
structure or class of problem *before* any USB name appears, USB macro/register names
(`USB_FORK_PORT_BRINGUP`, `USB_FORK_FW_SERVICE`, `USB_PORT_EN`, `CPUWRITE`/`APB_*`,
`USB_EP_CFG_DEFERRED`, etc.) appear only inside boxes explicitly labeled "USB
illustration," and the closing section of the skill states this discipline explicitly
so a future reader (or a future protocol's pattern author) cannot mistake the labeled
examples for Harness vocabulary to copy.

## How a skill-doctor / SKILL.md convention check would evaluate this

No `skill-doctor` (or similarly named) skill or script exists anywhere in this repo
(`grep -ril "skill.doctor|skill_lint|skill.*convention"` under `.claude/` returned
nothing) — `claude-plugin-skill-audit/SKILL.md` is the closest match by name but audits
*plugin/skill inventory and dependency scope*, not SKILL.md file conventions.

The nearest real, runnable check available in this environment is the `skill-creator`
plugin's `quick_validate.py` (frontmatter validator: required `name`/`description`,
kebab-case name ≤64 chars, description ≤1024 chars with no angle brackets, only
`name`/`description`/`license`/`allowed-tools`/`metadata`/`compatibility` keys
permitted). Ran it against both files:

```
python quick_validate.py .claude/skills/CORE/pattern-architecture
Skill is valid!
python quick_validate.py .claude/skills/CORE/command-generator
Skill is valid!
```

Measured against it directly: `name: pattern-architecture` (kebab-case, 20 chars),
frontmatter total 454 chars (limit 1024), `description` 362 chars (limit 1024),
`allowed-tools` is an accepted key. Both pass.

The superpowers `writing-skills` skill (loaded read-only for reference, not applied
verbatim) carries a different, stricter house style for its own plugin skills:
description must start with "Use when..." and describe only triggering conditions
(never summarize the workflow), and frequently-loaded skills should target well under
500 words. This repo's five sibling CORE skills
(`branch-mapper`/`interrupt-event-dispatch`/`vip-scenario-branch`/`command-inventory`/
`command-generator`) all use a declarative "Defines X" / "Generates X" description
instead, and are all loaded on-demand by topic match rather than into every
conversation — so the new skill deliberately follows the repo's own established
convention (declarative description, ~362 chars, one labeled illustration per generic
point, denser than the superpowers <500-word target) rather than the plugin's generic
style. A `writing-skills`-style reviewer would flag the description form and the word
count (skill body is 3692 words) as deviations from *its* default; a reviewer applying
this repo's own precedent (five already-shipped CORE skills of comparable or greater
density, several carrying "UNTESTED, generic placeholder" sections of their own) would
find it consistent. This is a real trade-off, not an oversight: the investigation's own
proposed section outline is exactly this dense, because the six trap classes each
need their own generic statement, USB illustration, and authoring rule to be actually
usable rather than a one-line pointer back to `USB_UVM_Handoff`.

Not run: the superpowers `writing-skills` RED-GREEN-REFACTOR pressure-scenario testing
(baseline-agent-without-skill vs. with-skill, on real pattern-authoring tasks) — that
is a substantially larger effort (subagent dispatch, multiple pressure scenarios,
iteration) outside this task's scope; flagging it here as the natural next step if this
skill's real-world effectiveness needs to be measured rather than structurally
inspected.

## Files touched

- `D:\DV\Task\DV_Agent_Harness_L5\v50\.claude\skills\CORE\pattern-architecture\SKILL.md` (new)
- `D:\DV\Task\DV_Agent_Harness_L5\v50\.claude\skills\CORE\command-generator\SKILL.md` (cross-reference added, frontmatter untouched)
- `D:\DV\Task\DV_Agent_Harness_L5\v50\CLAUDE.md` (consolidation-status paragraph updated)
- `D:\DV\Task\DV_Agent_Harness_L5\industrial\.claude\skills\CORE\pattern-architecture\SKILL.md` (synced)
- `D:\DV\Task\DV_Agent_Harness_L5\industrial\.claude\skills\CORE\command-generator\SKILL.md` (synced)
- `D:\DV\Task\DV_Agent_Harness_L5\PACKAGE\.claude\skills\CORE\pattern-architecture\SKILL.md` (synced)
- `D:\DV\Task\DV_Agent_Harness_L5\PACKAGE\.claude\skills\CORE\command-generator\SKILL.md` (synced)
