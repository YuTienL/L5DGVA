---
name: environment-handoff-distillation
description: Analyze a REAL, already-generated verification environment against the generic skill/agent that was supposed to have produced it -- extract where reality matched, where it diverged, and where terminology/methodology claims don't hold up -- then feed confirmed gaps back into the harness's own agents/skills/rules. The read-only counterpart to environment-packaging.
allowed-tools: Read Grep Glob Skill
---

# Environment Handoff Distillation

Most "learn from this environment" requests are really two different asks
that get conflated: (1) build a knowledge handoff -- a structured record of
what a real environment actually does, for a human or a future agent to
consult -- and (2) close the loop -- check whether the generic
skill/agent that was supposed to have generated this class of environment
still matches reality, and fix it if not. Do both, in that order; (2) is
worthless without (1) actually happening first with real evidence.

## Part 1 -- Build the handoff record

Read-only against the real environment. For each of the following, cite
`file:line`, never paraphrase from memory of what a similar environment
"probably" looks like:

1. **Generation methodology** -- read whatever `.claude/agents/` and
   `.claude/skills/` files exist inside (or were used to build) the real
   environment. Distinguish GENERIC (reusable for any IP/protocol) from
   PROJECT-SPECIFIC (hard facts about this one DUT/VIP pairing) content.
   Cross-check the generic skill's prescribed steps/deliverables against
   what actually exists on disk -- note every match and every divergence,
   not just the divergences (confirming what *did* work is equally useful
   signal for part 2).
2. **File/pattern structure and conventions** -- read several real
   examples (not one) of whatever the environment's "unit of test content"
   is (a pattern file, a sequence, a directed test), plus the framework code
   that dispatches them. If someone hands you a claimed structural
   description (e.g. "tests are organized as sections X/Y/Z"), verify it
   against the real dispatch code and real example files -- confirm the
   parts that are right, correct the parts that are wrong or incomplete, and
   say so plainly rather than forcing a fit. A claim being *directionally*
   right does not make it *structurally* accurate; report both where they
   diverge.
3. **Hardware-facing register/hierarchy facts** -- if the request involves
   understanding real RTL register/interrupt/event structure, trace the
   actual instance hierarchy and register bit-fields in the RTL source
   itself, using any existing design-note docs only as a reading-order
   shortcut, not as the source of truth. Report the concrete path and note
   any place the RTL's own inline comments contradict the RTL's own logic
   (this happens -- e.g. a bit-position comment that disagrees with the
   actual concatenation order two lines below it -- and is worth flagging
   as a live discrepancy, not silently resolved one way or the other).
4. **Claimed-methodology-vs-actual-practice gaps** -- when asked to confirm
   whether an environment follows some described best practice (e.g.
   "interrupt-driven waiting instead of polling"), check the ACTUAL call
   sites, not just whether the described mechanism exists in the codebase
   somewhere. A real case: the "correct" event-driven wait task existed,
   fully implemented, but had **zero real callers** -- every pattern that
   needed to detect the relevant transitions used register-polling instead.
   Reporting "the mechanism exists" without reporting "and nothing uses it"
   would have been actively misleading. Give a straight yes/no/mixed answer
   per case, with the real call sites (or their absence) as evidence.

## Part 2 -- Feed confirmed gaps back into the harness

Only after Part 1 produced grounded findings, ask: does anything here mean
`ip-uvm-dv-gen` (or another generic skill/agent) has an assumption that no
longer matches how real projects actually turn out? Concrete examples
already found this way:

- A generic skill assumed a fixed subdirectory nesting (e.g. "N build
  directories are children of DUT/"); the real project's own build system
  required those same N directories to be siblings of DUT/ instead, and the
  project's own maintainers had already documented this exact mismatch as a
  known open item. **When a real project has already found and documented a
  gap in the generic skill's assumption, that's a confirmed signal to update
  the generic skill** -- not just a one-off project quirk to route around
  silently.
- A generic agent's Step 1 mandated writing a specific settings block into
  the project's own CLAUDE.md ("write TARGET_IP/IP_PREFIX/DUT_ROLE/
  ATTACH_LAYER as the first thing a reader sees"); the real project's
  CLAUDE.md never contained any such block, and had instead organically
  grown a hand-written "lessons learned" rules list. This suggests the
  prescribed template was a reasonable starting point that real engineering
  practice outgrew -- worth noting as a template-vs-practice gap, not
  automatically "fixing" the real project's CLAUDE.md to match the
  prescription (the real project's evolved version may be the better
  artifact).
- A generic skill's terminology for describing test structure didn't
  exactly match the terms actually used in the real, evolved codebase
  (close, but not identical, and with one piece dropped in the informal
  restatement that turned out to be load-bearing in every real example).
  This is a signal to tighten the generic skill's own terminology/examples
  against a real corpus, not just to correct the one person's restatement.

When you find a genuine, evidence-backed gap of this kind: propose the
specific edit to the specific skill/agent file (quote the current text,
propose the replacement), rather than writing a new parallel mechanism.
This mirrors the harness's established preference (see `ip-uvm-dv-gen` and
the protocol-builder skill family) for extending/correcting existing
mechanisms over inventing new ones that duplicate them.

## What NOT to do

- Don't write the handoff record as prose summary without file:line
  citations -- a future reader (human or agent) needs to be able to verify
  or update it, not just trust it.
- Don't silently "fix" a real project's divergence from a generic skill's
  assumption during a read-only analysis pass -- report it; whether to fix
  the project, fix the skill, or leave both as they are is a decision for
  whoever owns that call, informed by your findings.
- Don't claim a methodology is or isn't followed based on the mechanism's
  mere existence in the codebase -- trace actual call sites.
