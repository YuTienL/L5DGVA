# RTL-First Architecture Discovery Gate -- Provenance Hardening

**Date:** 2026-09-01
**Scope:** `tools/verification_flow/rtl_first_architecture_discovery_gate.py` (real, wired gate for
the `ARCH_DISCOVERY` stage), plus its prompt contract in `dv_harness/prompts.py`.

## What was found

An earlier audit this session established that `rtl_first_architecture_discovery_gate.py` only
validated the *shape* of the agent's self-reported architecture-discovery evidence -- which
category flags (`auto_discovered_fields`) were set, whether every LOW/UNKNOWN `unknown_items` entry
carried a `next_action`, whether `architecture_evidence_db_generated` was true. None of that ties
back to real RTL text: an agent could invent plausible-looking module/port/interface/register-block
facts with zero RTL backing and pass identically to an agent that had actually read the source,
because `architecture_evidence_db_generated` was itself just another self-reported boolean.

Two adjacent files were read in full as part of scoping this fix:

- `tools/dut_architecture/build_architecture_model.py` -- consumes a `dut_extract` JSON (see below)
  and produces an `ArchitectureModel`-shaped document (`hierarchy`, `interfaces`, `clock_domains`,
  `reset_domains`, ... all heavily `"UNKNOWN"`/empty-list placeholder, confidence hardcoded to
  `"LOW"`). It infers protocol interfaces from a fixed keyword table matched against port-name
  substrings (`pcie`/`pipe`, `usb`/`utmi`, `axi`/`ahb`/`apb`, ...) -- a heuristic guess, not a
  citation-capable per-signal fact.
- `tools/real_env/dut_interface_extractor.py` -- a pure-regex Verilog/SystemVerilog scanner: three
  independent `re.finditer` passes over each `--rtl` file for `module <name>`,
  `parameter|localparam <name> = <value>`, and `(input|output|inout) ... <name>`. Output is three
  flat lists (`modules`, `ports`, `parameters`), each item carrying only `{"file": ..., ...}` --
  **no line number at all**. This confirms the earlier audit's finding verbatim: this chain's output
  shape has no per-fact line-range field to hang a citation off of, and its module/port items are
  file-level, not citation-precise -- wiring it in as the provenance source for this gate would need
  real schema work (adding line-number capture to the regex passes, restructuring
  `build_architecture_model.py`'s consumption of them), not a small patch. This chain also has zero
  current callers anywhere in the repo, confirmed by a repo-wide search.

Given that, the task scoped the fix as a lightweight, gate-local provenance check (grep/text
spot-check against the citation an agent supplies), explicitly deferring the deeper
`build_architecture_model.py`/`dut_interface_extractor.py` integration.

## What was built

`rtl_first_architecture_discovery_gate.py` now requires a new, mandatory evidence field:

```json
"architectural_claims": [
  {"kind": "MODULE", "name": "usb_top", "rtl_citation": "rtl/usb_top.v:12"},
  {"kind": "PORT", "name": "phy_clk", "rtl_citation": "rtl/usb_top.v:18-20"}
]
```

Validation, in `_verify_architectural_claim()`:

1. **Shape**: `kind` must be one of `MODULE`/`PORT`/`INTERFACE`/`REGISTER_BLOCK`; `name` and
   `rtl_citation` must be non-empty strings. A violation FAILs `ARCHITECTURAL_CLAIM_MALFORMED`.
2. **Citation format**: `rtl_citation` must match `path:start[-end]` (a trailing
   `":<digits>"` or `":<digits>-<digits>"`), with `start >= 1` and `end >= start`.
3. **File existence**: the cited path is resolved relative to the process's cwd -- matching
   `dv_harness/gates.py`'s `run_gate()`, which always `subprocess.run()`s every gate script with
   `cwd=str(root)` (the project root), the same convention `manual_lookup_before_edit_gate.py`'s
   `*_evidence_refs` already relies on. The path must exist as a real file.
4. **Line-range sanity**: the cited start line must not be past the end of the real file.
5. **Content spot-check**: the file's real text, within a +/-5-line tolerance window around the
   cited range (a citation is a pointer to "around here," not a promise of the exact line -- see the
   `test_citation_slightly_off_line_within_tolerance_still_passes` test), must contain the claimed
   `name` as a whole word (`\bname\b`). This is the actual provenance check: a claim naming a real
   file but citing a range where the name never appears (the audit's exact fabrication scenario)
   fails here.

Any check that doesn't hold FAILs the gate with a typed reason: `ARCHITECTURAL_CLAIMS_MISSING`
(field absent, not a list, or empty -- the field is unconditionally required, not optional),
`ARCHITECTURAL_CLAIM_MALFORMED` (shape problem in one claim), or **`UNVERIFIABLE_RTL_CITATION`**
(the citation itself doesn't check out -- bad format, missing file, out-of-range line, or the name
genuinely isn't near the cited lines), each carrying the offending `claim` and a human-readable
`detail`. All pre-existing checks (`RTL_SOURCE_REQUIRED_FOR_STEP5`,
`ARCHITECTURE_DOCUMENT_MUST_BE_OPTIONAL`, `RTL_DISCOVERY_TOO_SHALLOW`,
`USER_ASKED_BEFORE_RTL_EVIDENCE_SEARCH`, `UNKNOWN_ARCHITECTURE_WITHOUT_CALIBRATION_ACTION`,
`NO_ARCHITECTURE_EVIDENCE_DATABASE`, `ARCHITECTURE_LOCK_BEFORE_CALIBRATION`) are unchanged, same exit
codes, same output shape when everything else is satisfied.

`dv_harness/prompts.py`'s `ARCH_DISCOVERY` stage template was updated to show the new required
`architectural_claims` shape in its example evidence block (with a short bilingual explanation of the
requirement), so an agent following the prompt sees the real contract it must now satisfy.

## Ruling

**RULING:** `architectural_claims` is unconditionally mandatory (missing/empty FAILs), not an
optional/additive field defaulting to a silent no-op when absent. The house convention (see
CLAUDE.md / `generator.py`) of additive, byte-identical-when-absent schema changes is the right
default for *new capabilities*, but this is a security-hardening fix for a confirmed fabrication
gap -- an optional citation requirement an agent could simply omit would not close that gap at all
(it would just add an unused field). This matches how this codebase's other provenance gates
(`manual_lookup_before_edit_gate.py`'s `*_evidence_refs`) already treat evidence-ref-style
requirements: mandatory once the underlying fabrication risk is confirmed real. A repo-wide search
confirmed no existing test or `STAGE_GATES` caller supplies a full evidence payload for this specific
gate today, so this is not a breaking change to any currently-exercised path.

**Out of scope (explicit follow-up):** wiring `build_architecture_model.py`/
`dut_interface_extractor.py` as the actual source of `architectural_claims` (auto-deriving claims
+ citations from a real RTL parse instead of an agent typing them by hand) is deferred. It requires
real schema work on the extractor side (adding line-number capture to its three regex passes is the
minimum; the model builder's `"UNKNOWN"`-heavy heuristic interface inference would also need
citation-precision work) that the earlier audit already correctly flagged as more than a wiring fix.
This lightweight spot-check only verifies an *agent-supplied* citation resolves to real content; it
does not (and is not intended to) replace a real RTL-parsing chain, nor prove the agent's semantic
understanding of what it cited.

## Tests

New file: `dv_harness_tests/test_rtl_first_architecture_discovery_gate.py` -- 22 tests, all via real
subprocess invocation of the gate script (no mocking), each against a real filesystem fixture
(`tmp_path`-rooted `.v` files with real module/port declarations at known line numbers):

- 5 regression tests for every pre-existing shape-only FAIL branch (still pass unchanged).
- `ARCHITECTURAL_CLAIMS_MISSING`: field absent, and field present-but-empty.
- `ARCHITECTURAL_CLAIM_MALFORMED`: missing `kind`, invalid `kind`, missing `name`.
- `UNVERIFIABLE_RTL_CITATION`: nonexistent file, fabricated name near a real citation (the audit's
  core scenario), malformed citation text, line range past end of file, backwards range, a name far
  outside the tolerance window.
- Tolerance-window PASS case (citation a couple of lines off from the real declaration still
  passes) and a multi-claim case (first bad claim reported, not silently skipped).
- `INTERFACE`/`REGISTER_BLOCK` kinds accepted; full end-to-end PASS with `lock_requested` +
  `calibration_complete` both true.

### Full suite run

```
python -m pytest dv_harness_tests/ -q
```

Result: **1473 passed**, 0 failures, in 701.18s -- confirming zero regressions across the full
existing test suite, not just the new/touched files.
(`dv_harness_tests/test_rtl_first_architecture_discovery_gate.py` -- 22 new tests -- and
`dv_harness_tests/test_hard_gate_script_smoke.py`/`test_engine_gates_and_routing.py` -- 365 tests,
which exercise this exact gate script and its registry entry -- were run individually first and
confirmed green before the full-suite run.)

## Residual gaps / concerns

- The content spot-check is a `\bname\b` substring search over a small line window -- it is
  deliberately lightweight (per the task's own framing) and can be fooled by a name that
  coincidentally appears nearby for an unrelated reason (e.g. citing a comment that happens to
  mention the name). It closes the cheap, common fabrication case (inventing a name with zero
  textual basis anywhere near the citation) but is not a semantic RTL check.
- Real RTL-parsing-chain integration (`build_architecture_model.py` /
  `dut_interface_extractor.py`) remains unwired, as explicitly scoped out of this task and noted
  above as a follow-up.
- No project-root-relative test exercises the gate under the *actual* production `cwd=root`
  convention (`dv_harness/gates.py`'s `run_gate()`); tests instead pass `cwd=tmp_path` directly to
  the subprocess, which exercises the identical relative-path-resolution code path without touching
  the real repo tree. This is a deliberate, lower-risk test design choice, not a gap in the
  mechanism itself.
