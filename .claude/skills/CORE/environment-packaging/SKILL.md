---
name: environment-packaging
description: Package a working (often messy, actively-debugged) UVM verification environment into a clean, minimal, DE-facing deliverable in a NEW directory -- read-only on the source. Turns IP_UVM_DV_Gen's aspirational "Packaging" prose into concrete classification rules, grounded in a real USB VIP environment case study.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---

# Environment Packaging

The operational companion to `ip-uvm-dv-gen`'s "Packaging" section, which
only describes intent ("a script that wipes and rebuilds... refuses to write
if verification fails") with no actual classification rules. This skill
supplies those rules, derived from packaging a real, live USB VIP-based
environment (lan063/DWC_usb31) as the worked case study.

## Non-negotiables

1. **The source is read-only, always.** A real environment worth packaging
   is usually still under active development -- check file mtimes before you
   start; a cluster of files touched in the last 1-3 days, or a
   `scripts/`-style directory with 50+ `tmp_*`/`watch_*`/`check_*` files, is a
   live debug session, not a finished artifact. Never write, edit, delete, or
   rename anything under the source tree. All output goes to a **new**
   directory.
2. **Classify by evidence, not by filename guessing.** For "is this file
   needed to run," read the actual build entrypoint (Makefile / run script)
   and grep for what it references -- do not classify by name pattern alone.
   For "is this a process record vs a deliverable," open the file and read
   its content; a `.svh` with a long header comment describing *design*
   is a deliverable, a `.md` narrating a dated bug investigation with
   "Correction, added later" annotations is a process record, regardless of
   which directory either lives in.
3. **Vendor-licensed or access-controlled content is opt-in, not opt-out.**
   If a "Doc" or reference tree contains hard-macro delivery packages,
   `password.txt`, GDS/`macro_views`/`pads_fc_views` material, or anything
   else that looks like a separately-licensed vendor deliverable, do NOT
   include it by default. Ask the user explicitly. (Real case: a USB
   environment's `Doc/` held genuine USB/xHCI/UTMI spec PDFs *and* several
   `dwc_*` PHY hard-macro packages with a `password.txt` sitting alongside
   them -- excluded by explicit user decision, not by the skill's own guess.)
4. **Fix structural bugs when you copy, don't perpetuate them.** A source
   tree that is itself a staging/authoring copy may not satisfy its own
   build system's structural requirements (e.g. a documented "N directories
   must be direct siblings under DUT_ROOT_PATH" rule, while on disk some of
   those N directories sit one level higher, as siblings of DUT/ rather than
   its children). Since the package is a fresh copy, it is safe -- and
   correct -- to reorganize into the structurally valid shape the build
   system actually requires, rather than shipping the same broken layout
   the DE would then have to debug themselves.

## Classification rules (concrete, from the case study)

### RUN_NEEDED vs DEV_SCRATCH (a `sim/`-style build/run directory)

Read the Makefile/run-script in full; every file it names by path (as an
input, a generated-output location it must pre-exist, or a `$(error)`-guard
target) is RUN_NEEDED. Everything else in that directory earns DEV_SCRATCH
by two independent signals, either one sufficient:
- **Naming family**: `tmp_*`, `watch_*`, `check_*` (unless individually
  invoked BY the build), `build_*.log`, `run_*.log`, `query_*.log`,
  `kill_*.log`, `scratch_*`, `refpoll_*` -- these are investigation-session
  artifacts, not reusable infrastructure.
- **Content**: a script that hardcodes one specific job ID, one specific
  FSDB filename, or a colleague's home-directory path is a one-shot
  investigation aid, not part of the reusable environment, no matter what
  it's named. Read a sample before trusting a naming-only classification.

Two items each require their own judgment call, not a blanket rule:
- **Generated artifacts** (e.g. a `__pycache__`, or a `.svh` a script
  regenerates from a registry file with a "DO NOT EDIT" header) -- omit;
  they regenerate on first use and shipping them risks a stale copy winning.
- **Operator workflow tools** (e.g. a PC<->server file-sync/relay script that
  isn't referenced by the Makefile but is real, documented, and used by
  every session) -- these usually should ship, since the DE receiving the
  package likely works the same split-workstation way; note the assumption
  explicitly rather than silently deciding either way.

### PROCESS_RECORD vs DELIVERABLE (a `docs/`-style directory)

Read every file's content, not its name. Deliverables are: the actual user
guide, the actual verification plan, generated reference matrices/pool
files, and any `.svh`/`.sv` design documentation embedded as source header
comments (these describe the environment itself). Process records are:
dated investigation narratives, punch-lists with resolution-status columns,
"Correction, added later"-style self-retractions, onboarding/session-startup
checklists full of incident anecdotes, and README files that are navigation
indexes *over* those narratives.

**If the requester says "no `*.md`" (or any other blanket format
exclusion), honor it literally** -- do not use your own DELIVERABLE
classification to smuggle a `.md` back in because you judged its content
valuable; fold that content into whichever consolidated document format
*is* being shipped (the user guide, the English install README) instead of
keeping it as a separate file in a format the requester explicitly excluded.

### Doc/Spec material

Keep genuine protocol/interface specifications and register reference
sheets. Exclude anything that reads as a separately-controlled vendor
deliverable (see Non-negotiable 3) and anything scoped to an unrelated
subsystem that happened to be co-located (e.g. a full-chip source tree's
`Doc/` holding another IP's register docs).

## Regenerating the User Guide and Verification Plan

Do not hand-edit stale prose. Cross-check every numeric claim in an existing
guide against the CURRENT source of truth before reusing it:
- Pattern/test counts against the actual pattern registry file, not the
  guide's own prior count.
- Verification-plan item/section/status counts against the live
  spreadsheet's actual rows, not a cached summary paragraph.
- Every worked example command against the actual dispatch mechanism (does
  the named pattern/test actually exist in the registry today?).

A real guide audited during the case study had, simultaneously: a pattern
count quoted as 69 in one section and 92 (the correct, current number) two
sections later; a vPlan summary citing "four sheets" when the live
workbook had five; a worked example invoking a pattern that had been
superseded and was no longer registered; and a front-matter status banner
claiming the environment "compiles and simulates" while a back-matter note
in the same document said "nothing has been compiled yet." **Treat this
class of drift as expected in any organically-maintained guide, not an
anomaly** -- verify before republishing, and prefer removing an unverifiable
claim over carrying it forward.

## Writing the English install README

Ground every section in what you can actually verify, not the generic
template. At minimum:
- **Environment variables**: read the actual build entrypoint for every
  variable it references (paths, EDA tool homes, arch selectors) --
  don't just list the generic `DUT_ROOT_PATH`/`VIP_HOME`/`UVM_ROOT_PATH`
  triad if the real Makefile has more (license vars are often deliberately
  *not* referenced in-repo -- site setup handles those externally; say so
  rather than inventing a `LM_LICENSE_FILE` line that isn't actually used
  here).
- **DUT-side integration hooks**: confirm the actual hook content in the
  real source before describing it -- a generic skill's example (e.g. an
  appended filelist line using an environment-variable path) may not match
  what the real hook actually contains (e.g. a relative path resolved
  against the build's working directory instead). Don't assume the generic
  form; grep for the hook marker and quote the real line.
- **Run commands per mode**: give exact, verified command lines for every
  major mode the requester cares about (e.g. each protocol speed grade),
  cross-checked against the real dispatch mechanism, not paraphrased.
- **Debug tooling**: give the actual debug-tool invocation this environment
  uses (e.g. exact Verdi/waveform-viewer flags), including any site-specific
  quirks discovered during analysis (e.g. "this site's Verdi refuses to
  launch without an LSF option").

## After packaging: verification handoff

Once the package exists, launch an independent completeness check (see
`environment-handoff-distillation` for the broader knowledge-extraction
version of this idea) -- confirm every path the build entrypoint references
actually exists in the package, confirm no excluded file is silently
required by something that shipped, and confirm the package's directory
layout genuinely satisfies whatever structural contract its own build
system documents (see Non-negotiable 4).
