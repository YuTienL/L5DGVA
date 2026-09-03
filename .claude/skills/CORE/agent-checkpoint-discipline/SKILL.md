---
name: agent-checkpoint-discipline
description: Required convention for any agent expected to run more than a handful of rounds (a long build/investigation agent, not a quick one-shot task) -- maintain a structured, continuously-updated resume-state artifact so a lost/unresumable session can be re-briefed from disk alone, with nothing left only in conversation state. Codifies the real worked pattern that already saved a real session (usb31_dev_uvm's CLAUDE.md trap catalogue + docs/dut-request.md) as the formal required schema, and points at the checker script that verifies an artifact actually exists and is current.
allowed-tools: Read Grep Glob Edit Write PowerShell
---

# Agent Checkpoint Discipline

## Why this exists (the incident)

A real IP_UVM_DV_Gen build agent, investigating the TCA NC->USB hang in
`usb31_dev_uvm` this session, became **permanently unresumable mid-
investigation** -- a real `No transcript found for agent ID` failure on
`SendMessage`, after the agent had accumulated many hours of context. A
fresh agent had to pick the investigation back up from nothing but the disk
state the lost agent left behind.

It recovered reasonably well, because the lost agent's own documentation
habits happened to already be thorough: `usb31_dev_uvm/CLAUDE.md`'s trap
catalogue, `uvm/docs/dut-request.md`'s open-items list, and in-code
retraction comments together carried enough state for the fresh agent to
reconstruct exactly where the investigation stood. **But that recovery was
a side effect of one agent's general good practice, not a checked, required
convention.** A less disciplined agent losing its session the same way would
have had no formal fallback, and the investigation's hours of work would
have been unrecoverable. This skill turns the accident into a requirement.

## Who this applies to

Any agent expected to run more than a small number of rounds, or to span
more than one wall-clock session: a build agent, an investigation/debug
agent chasing a hang or a root cause, a multi-hour environment-generation
agent. It does **not** apply to a quick one-shot lookup, a small single-file
edit, or any task where losing the session costs nothing worth
reconstructing.

Concretely in this harness: `IP_UVM_DV_Gen` and any build/debug agent it
dispatches for long-running work (see its own reference to this skill).
Any other agent definition whose own work is open-ended and long-running
should adopt the same convention.

This is a different mechanism from `dv_harness/session_snapshot.py`'s
engine-level auto-checkpointing. That module snapshots **this harness's own
engine loop** -- `state.json`, `blackboard/`, `plans/`, `react/`, `agents/`,
`lsf/`, all rooted at a DVHarness project's own `.dv-harness/` -- at
`DVHarness.run_stage()`/`loop()` stage transitions. It has no reach into a
**separately-dispatched, long-running Agent-tool subagent's own accumulated
context**, working inside an arbitrary build tree that may not even be a
DVHarness project (`usb31_dev_uvm`, the real case this skill is built from,
has no `.dv-harness/` of its own). The two are complementary, not
duplicates: session_snapshot.py resumes the engine; this skill's convention
resumes a dispatched agent's own investigation.

## The required artifact: schema

A resume-state artifact must carry all five of the following, kept current
(see "Update cadence" below), so a completely fresh agent (or a human) can
answer each question from the artifact alone, without reading the whole
session's history:

1. **Current hypothesis / status** -- what is currently believed to be true
   or false, and the open/closed/resolved state of each active line of
   investigation.
2. **Evidence gathered so far, with citations** -- every fact a `file:line`
   (or databook page, or run log) citation, never a paraphrase from memory.
3. **Next planned step** -- what the investigation was about to do next,
   concretely enough that a fresh agent does not have to re-derive it.
4. **Decisions pending user/coordinator confirmation** -- anything that
   needs a human (or a coordinating agent) to decide before work can safely
   continue, named explicitly rather than left implicit.
5. **Files touched this session** -- what has actually been edited so far,
   so a fresh agent knows what state the tree is already in before touching
   anything further.

A section does not need a literal header spelled exactly like the schema
name above -- see the worked example next, which satisfies every one of
these five using its own organic vocabulary.

## The real worked example, annotated against the schema

`usb31_dev_uvm/CLAUDE.md`'s **trap catalogue** (`T-1` through `T-31`, each
entry a numbered, cited finding) and `usb31_dev_uvm/uvm/docs/dut-request.md`'s
**open items** (`ENV-`/`DUT-`/`VIP-`/`DOC-`-numbered, grouped
blocking-compile / blocking-verification / not-blocking) together are the
real artifact that let a fresh agent resume this session's own lost
investigation. Mapped onto the schema:

| Schema section | Where it lived in the real artifact |
|---|---|
| Current hypothesis / status | `dut-request.md`'s per-item status line, e.g. `DUT-011 -- the TCA never acknowledges the NC->USB switch` with "Bridge state at timeout: 44 writes done...", and items explicitly marked `CLOSED`/`RESOLVED BY EVIDENCE` once settled (`ENV-001`, `DUT-003`) |
| Evidence gathered, with citations | `CLAUDE.md`'s trap catalogue -- every `T-N` entry cites `file:line` (`T-28`: `` `tca_apb_pready` is tied to `1'b1` inside `tca_reg` (`DUT/RTLCAT/SS_VOUT_USB_PHY.v:59861`) ``) |
| Next planned step | `dut-request.md`'s **`To close:`** field on every open item -- e.g. `DUT-011`'s "Remaining candidates: `tca_clk` not running; or the pending PoR request not being overridden" |
| Decisions pending confirmation | `dut-request.md`'s `Owner:` field, especially where marked jointly (`DUT-005`: "Owner: DV owner + RTL owner jointly" -- with an explicit warning that "answering an unrelated question can silently remove" the fallback if nobody flags it) |
| Files touched this session | `CLAUDE.md`'s own convention of citing `grep -rn "DV_UVM HOOK"` as the authoritative list of this environment's edits (T-2), and `dut-request.md`'s `ENV-001` stating exactly what was and was not modified in the delivered tree |

This is precisely *why* the fresh agent could be re-briefed successfully:
reading these two files alone reconstructed the investigation's full state,
with nothing lost that lived only in the dead session's own context window.

## File location convention

Two recognized layouts. Use whichever the build tree has already grown; do
not force a migration between them mid-investigation.

- **Dual-file (preferred where a project is already this shape, and the
  pattern to default to for a new long-running build)**:
  - `<build_tree>/CLAUDE.md` -- the durable, append-only evidence/citation
    log (the "trap catalogue"). Entries are never deleted, only added to;
    a retraction is a **new** entry stating what was retracted and why
    (per the real `T-31` lesson: "the fix did nothing" and "the fix was
    destructive" look identical from a bare readback, so the retraction
    itself is evidence worth keeping, not history to erase).
  - `<build_tree>/uvm/docs/dut-request.md` (or `<build_tree>/docs/dut-request.md`
    if there is no `uvm/` subtree) -- the mutable, status-tracked open-items
    list. Items here **do** get edited in place: `OPEN` becomes `CLOSED` /
    `RESOLVED BY EVIDENCE`, `To close:` gets updated as the plan changes.
- **Single-file fallback**, for a build tree that has not already grown the
  dual-file convention organically: `<build_tree>/RESUME.md` or
  `<build_tree>/STATUS.md` (at the tree root, or under a `docs/`
  directory), carrying all five schema sections in one file.

## Update cadence

Update the artifact **after every round that changes the investigation's
state** -- a new hypothesis formed, new evidence gathered, an inference
confirmed or refuted, a fix attempted and its outcome observed, a file
edited. Not only at the end of the session, and not on a fixed round-count
timer.

Concrete test: if a fresh agent reading the artifact as it currently stands
would be missing something that happened in the last round -- a citation,
a status change, a retraction, a newly-pending decision -- the artifact is
overdue for an update. A round that is pure mechanical re-execution with no
new state (rerunning an unchanged build, re-reading a file already cited)
does not need its own update.

## Verification

`dv_harness/agent_checkpoint_check.py` (`python -m
dv_harness.agent_checkpoint_check <build_tree>`) is the checkable half of
this convention: given a build-tree path, it reports whether a resume-state
artifact exists at one of the recognized locations, whether it carries all
five schema sections (evidence citations checked by density, the other four
by keyword/pattern -- not by requiring a literal header, so the real
`CLAUDE.md`/`dut-request.md` example passes on its own organic wording), and
whether its own modification time is stale relative to other recently-
touched files in the tree (excluding the vendor/read-only `DUT/`/`VIP/`
directories this same generator process already treats as out of scope for
edits). See `dv_harness_tests/test_agent_checkpoint_check.py` for the
synthetic-fixture test suite, including a read-only positive check against
the real `usb31_dev_uvm` tree.

Run it before ending a long build/investigation agent's session (a clean
exit with a stale or incomplete artifact defeats the whole point), and as
a periodic audit of any in-flight long-running build tree.

## What NOT to do

- Don't treat "the agent is thorough and writes good comments anyway" as
  sufficient -- that is exactly the accident this skill turns into a
  requirement, because it is not something a checker (or a coordinator) can
  rely on across every agent and every session.
- Don't write the artifact once at the start and never touch it again --
  a resume-state artifact that reflects round 1's state after round 40 is
  worse than no artifact, because it actively misleads a fresh reader
  rather than leaving them to ask.
- Don't delete an evidence entry that turns out to be wrong -- retract it
  with a new, dated entry explaining the retraction (see `T-31`'s own
  lesson: a retraction's reasoning is itself evidence a fresh reader needs).
- Don't invent a third file-location convention for a project that already
  has the dual-file layout established -- extend what is there.
- Don't substitute a vague "in progress" status for a real hypothesis/
  evidence/next-step breakdown -- the schema exists so a fresh agent does
  not have to re-derive the investigation from raw logs.
