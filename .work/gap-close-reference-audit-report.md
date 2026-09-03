# Report: Reference-pattern coverage audit tool (Gap #1 closed)

Scope: close the confirmed gap that `reference/bfm_patterns/*.txt` files (the DE-provided
originals) were only ever consulted reactively, bug by bug, never with an upfront systematic
pass — the specific real cost being 3 real debugging rounds to find that `usb_p2_switch_en`
is written on the host-side TCA register but never on the DUT-side TCA register in any
HS-speed pattern.

## What was built

1. **`dv_harness/reference_pattern_audit.py`** — new module, two layers:
   - **Extraction** (`extract_register_writes`/`extract_directory`): mechanically parses
     every register-write-style macro call (`` `CPUWRITE<N>B(...)``, `` `HOSTWRITE<N>B(...)``
     and any other `<PREFIX>WRITE<N>B(<addr>, <value>); //<comment>` call — the regex is
     generic on PREFIX, not a hardcoded macro list) into a `RegisterWrite` record:
     `{file, line, macro, address_or_register, value, host_or_dut_context, base, offset,
     comment, commented_out}`. Grounded against the real syntax by reading
     `USB2_bulkin.txt`/`USB2_bulkout.txt` under
     `D:/DV/Task/USB/usb31_dev_uvm/reference/bfm_patterns/` directly before writing any regex
     — the macro call idiom, the `HOSTWRITE`/`CPUWRITE` host-vs-DUT naming convention, and the
     `<base>_<offset>` underscore-delimited address convention were all confirmed there, not
     guessed.
   - **Symmetry/coverage detector** (`discover_paired_blocks`/`find_symmetry_asymmetries`):
     generically pairs a HOST-context base address with a DUT-context base address by
     Jaccard-similarity of their corpus-wide write-offset sets (never a hardcoded
     base-address table — e.g. host base `161A` and DUT base `1272` are paired because they
     write the same offset set `{0004, 0008, 0010, 0014, 0020}` across the corpus, jaccard
     1.0), then does a **per-file** symmetry check: for each paired block and each file that
     touches either side, flags any offset written on one side in that file but never on the
     paired base in that same file. Per-file (not corpus-aggregate) is the deliberate design
     choice that makes this reproduce the real bug — see "Verification" below for why an
     aggregate-only check would have missed it.
   - `audit_directory()` is the single entry point (extract → pair → flag → JSON-serializable
     result dict with a `summary.verdict` of `CLEAN`/`ASYMMETRY_FOUND`); `format_report()`
     renders the same result as a human-readable report, matching this codebase's
     `explain`/`checklist` JSON-plus-human-readable convention.

2. **CLI**: `dv-harness reference-audit <pattern_dir> [--glob GLOB] [--json]`, wired in
   `dv_harness/cli.py` matching the existing `self-audit`/`preflight` convention (JSON or
   human-readable output, exit 1 on any finding so it can gate a pipeline). Verified
   `--help` output and that the full CLI argparse tree still collects/parses cleanly after
   the insertion.

3. **Required workflow step**: `.claude/agents/IP_UVM_DV_Gen.md` Step 7 ("Wrap VIP sequences,
   then convert the BFM patterns") now opens with a new **"Required first: the
   reference-pattern coverage audit"** subsection, stated with the same "Required, not
   optional... same weight as this document's other required steps" language as the rest of
   the document's required-step callouts — `dv-harness reference-audit <dir>` must be run and
   its findings reviewed/resolved before the existing "Converting"/"Prove equivalence" work
   proceeds. Cites the real `usb_p2_switch_en` finding as the concrete motivating example and
   points at this report and the real-content test for verification.

4. **Tests** — `dv_harness_tests/test_reference_pattern_audit.py`, 13 tests, all passing:
   - 10 unit tests against a small **synthetic** fixture (host/DUT base pair `AA00`/`BB00`,
     never real project content) proving: macro/addr/value/comment/context/base/offset
     parsing; READ-call exclusion from the write set; commented-out-call detection and its
     exclusion from both pairing and coverage; correct pairing discovery; a HOST-only field
     flagged; a DUT-only field flagged; a shared field never flagged; a commented-out write
     never counted as coverage; end-to-end `audit_directory`/`format_report` shape.
   - 3 tests are the **real integration test** against the actual
     `D:/DV/Task/USB/usb31_dev_uvm/reference/bfm_patterns/` directory (read-only; skipped, not
     failed, if that directory is absent on the machine running the tests — it lives outside
     this repo), matching this project's own established precedent
     (`test_makefile_to_run_profile.py` asserting against the real template Makefile rather
     than a synthetic fixture). These assert the tool actually discovers the real HOST
     `161A`/DUT `1272` TCA pairing from real evidence, and flags all 8 real HS-speed
     (`USB2_*.txt`) pattern files with a host-only `usb_p2_switch_en` write at offset `0020`
     while correctly leaving the real SS-speed pattern (`USB3_susres.txt`, which genuinely
     writes both sides) unflagged.

## Verification: does it reproduce the known real finding?

**Yes — confirmed by running the tool against the real
`reference/bfm_patterns/` directory** (24 real files, read-only):

```
Reference-pattern coverage audit: D:\DV\Task\USB\usb31_dev_uvm\reference\bfm_patterns
  files scanned: 24
  register writes extracted: 2932 (2731 active, 201 commented-out)
  host/DUT paired register blocks discovered: 1
    HOST base 161A <-> DUT base 1272 (jaccard=1.0, shared_offsets=['0004', '0008', '0010', '0014', '0020'])

VERDICT: ASYMMETRY_FOUND -- 12 finding(s):
  [USB2_bulkin.txt] offset 0020 written HOST-side (base 161A) but NEVER DUT-side (base 1272)
    in this file -- citation: HOSTWRITE4B(32'h161A_0020) at line 79 // usb_p2_switch_en=1, ss_hdshk_req=0
  [USB2_bulkout.txt] ... (same, line 79)
  [USB2_con.txt] ... (same, line 79)
  [USB2_interruptin.txt] ... (line 84)
  [USB2_interruptin_ep1.txt] ... (line 94)
  [USB2_interruptin_intervel3.txt] ... (line 83)
  [USB2_interruptout.txt] ... (line 83)
  [USB2_isochin.txt] ... (line 80)
  [USB2_isochin_intervel3.txt] ... (line 80)
  [USB2_isochin_xfernotready.txt] ... (line 91)
  [USB2_isochout.txt] ... (line 84)
  [USB2_susres.txt] ... (line 113)
```

That is exactly the known real finding: every HS-speed (`USB2_*.txt`) pattern writes
`usb_p2_switch_en` on the host TCA offset `0x161A_0020` and never on the DUT TCA offset
`0x1272_0020` in that same file. Two files were independently checked by hand before trusting
the tool's own output:

- `USB2_susres.txt` line 114 has the DUT-side write present but **commented out**
  (`` //`CPUWRITE4B (32'h1272_0020, ...) ``) — the extractor correctly marks it
  `commented_out=True` and excludes it from coverage, so this file is still (correctly)
  flagged.
- `USB3_susres.txt` (SS-speed) and `USB31_SSPcon.txt` (SS-speed) both have the DUT-side write
  **present and live** at line 145/83 respectively — these are correctly **not** flagged,
  proving the detector is precise, not a blanket "base 1272 is incomplete somewhere" flag.

**Why the per-file (not corpus-aggregate) design was necessary**, discovered while building
this tool: offset `0020` on DUT base `1272` *is* written somewhere in the corpus
(`USB3_susres.txt`), so a naive corpus-wide "is this offset ever covered on both sides
anywhere" check would see it as covered and miss the bug entirely. The detector instead uses
the corpus-wide pairing only to learn *which two bases are the same logical block* and *which
offsets are known-relevant to that block*, then re-checks host/DUT symmetry independently
**within each file** — which is what actually reproduces the real finding.

## Files changed

- `dv_harness/reference_pattern_audit.py` (new)
- `dv_harness_tests/test_reference_pattern_audit.py` (new)
- `dv_harness/cli.py` (added `reference-audit` subcommand: parser definition + dispatch
  handler; no other subcommand's definition touched)
- `.claude/agents/IP_UVM_DV_Gen.md` (added the required "reference-pattern coverage audit"
  subsection at the top of Step 7)

`dv_harness/cli.py`, `.claude/agents/IP_UVM_DV_Gen.md`, and `CLAUDE.md` all had pre-existing
uncommitted changes from other concurrent workstreams in this session at the time of this
edit (confirmed via `git status --short`/`git diff` before editing, per this workflow's own
instructions) — edits above were scoped narrowly (new insertions at specific, unrelated
anchor points) so as not to touch or conflict with that other in-flight work. No commit was
made as part of this task; the changes are left staged in the working tree for the
orchestrating/coordinating session to commit alongside the other gap-closure work, per this
project's Methodology Consolidation Rule ("closed together").

## Test results

```
$ python -m pytest dv_harness_tests/test_reference_pattern_audit.py -v
...
13 passed in <2s
```

Also confirmed: `python -m pytest dv_harness_tests --collect-only -q` still collects all 2676
tests cleanly (no import/syntax breakage introduced by the `cli.py` edit), and
`dv-harness reference-audit <real-dir>` exits 1 (asymmetry found) / would exit 0 on a clean
directory, matching the `self-audit`/`preflight` gate convention.

## Status: DONE

Tool built, wired into the CLI, wired into `IP_UVM_DV_Gen.md`'s Step 7 as a required (not
optional) step, and **verified to reproduce the real, known `usb_p2_switch_en` host/DUT TCA
asymmetry** against the real `reference/bfm_patterns/` directory — not a synthetic
stand-in for it.
