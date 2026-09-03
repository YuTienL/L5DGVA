# run_profile.json + justfile generation

Machine-readable IR of a generated UVM environment's single authoritative
execution surface (its Makefile today; an SoC-level reference command.txt
is the same shape for a future SYSTEM_LEVEL_MODE case). Exists so an agent
never composes a vcs/simv command line, or invents a plusarg, from
documentation or a paraphrase -- it may only use params/targets present in
a run_profile.json that was itself mechanically extracted from a real
source file, and may only invoke that environment through the justfile
generated from it. A knob believed missing is a question-queue item, never
something an agent adds to either file itself.

## Why this exists (asset-processing context)

Verification assets split into three kinds that must be processed
differently: executable facts (a Makefile, a real sim.log), spec intent
(a register/programming-guide doc), and reference implementations (VIP
examples). Mixing them into one undifferentiated context blob is the most
common failure mode -- an agent that reads a *description* of how to build
the simulator and one that reads the *Makefile that actually builds it* are
not doing the same task, even when both look like "understanding the build
system." `run_profile.json` is the normalized IR for the first kind
(executable facts) as it applies to "how do I actually invoke this
environment" -- never for the other two.

Authority order when documentation and the real source disagree (highest
first): 1) elaboration/actual simulation result, 2) the reference
Makefile/command.txt itself, 3) DUT RTL, 4) register file (DUT then
Global), 5) existing testbench binds, 6) controller doc/programming guide,
7) IP user guide, 8) VIP example, 9) VIP document. `run_profile.json` sits
at tier 2 by construction -- it is a lossless, mechanical reflection of the
Makefile, never an independent guess.

## Pipeline

```
Makefile (or command.txt)  --[makefile_to_run_profile.py]-->  run_profile.json
run_profile.json           --[run_profile_to_justfile.py]-->  justfile + validate_run_profile_args.py
```

1. **`dv_harness/uvm_generator/schemas/run_profile.schema.json`** -- the
   JSON Schema (draft 2020-12). Fields: `source` (which real file this was
   extracted from + its content sha256, so a stale profile is detectable),
   `target` (TARGET_IP/IP_PREFIX/TOPMOD/EXTRA_TOPS), `required_paths`,
   `compile_time_params` vs `runtime_params` (the rebuild-required
   distinction the source Makefile itself encodes via its own "Runtime
   variables (no rebuild needed)" / "DUT specification variables (rebuild
   required)" section banners), `defines`, `compile_flags`, `lsf`,
   `pattern_registry`, `constraints` (enum_membership / retired /
   mutual_requirement / forbidden_combination, reverse-derived from the
   source's own `$(error ...)` guard blocks -- verbatim message text, never
   a paraphrase), and `targets` (the only verbs an agent may invoke, one
   per real `.PHONY` entry).

2. **`dv_harness/uvm_generator/run_profile.py`** -- load/save/validate
   (via `jsonschema`), plus `find_param()`/`check_constraints()` query
   helpers other tooling builds on. `load_run_profile()`/`save_run_profile()`
   never let an invalid profile reach disk or be trusted from disk.

3. **`dv_harness/uvm_generator/makefile_to_run_profile.py`** --
   `extract_run_profile(makefile_path, target_ip, ip_prefix)`. A pattern
   extractor, not a Make-language interpreter: it recognizes the concrete
   idioms confirmed present in this project's own generic template
   (`dv_harness/uvm_generator/templates/sim_scripts/Makefile`, itself a
   real chip-genericized copy of the USB_UVM_Handoff proving-ground
   Makefile) -- `?=` defaults (including indented ones inside `ifneq/else`
   blocks), `ifndef`+`$(error)` required-path guards, `ifeq($(filter
   $(VAR),a b c),)` enum guards, the real `RUN_FLAGS := +PATTERN=$(PATTERN)
   +UVM_TESTNAME=$(TEST) ...` plusarg bindings (scanned from the file, never
   assumed as a UVM convention), and multi-line `.PHONY:` declarations
   (backslash-newline joined first, per GNU Make's own line-splitting rule).
   Anything it cannot confidently classify is simply absent from the
   output, never guessed.

4. **`dv_harness/uvm_generator/run_profile_to_justfile.py`** --
   `generate_justfile(profile)`. Each modeled target (`compile`, `sim`,
   `regress`, `check`, `clean`, `distclean`, `list_patterns`, `help`) gets a
   `recipe *args:` -- **variadic passthrough, not typed named parameters**.
   A typed-parameter design (`compile speed="ss_capable" ...`) was tried
   and rejected: `just` recipe parameters are positional, so `just compile
   speed=gen1` binds the *entire literal token* `"speed=gen1"` to the first
   positional parameter rather than reading it as `KEY=value` the way
   `make compile SPEED=gen1` does -- confirmed by a real `just --dry-run`
   run producing `SPEED=speed=gen1`. Passthrough keeps the real Makefile
   variable names as the actual interface and leaves defaults owned by the
   Makefile's own `?=`, never duplicated in the justfile.
   Every recipe calls `validate_run_profile_args.py` first and only reaches
   `make` if that exits 0. A `human_raw_override` recipe exists for a human
   operator reaching an unmodeled real target (e.g. `verdi`, `cov_gui`) --
   loudly commented as human-only; an agent using it instead of a modeled
   recipe is bypassing the reason this file exists.

5. **`dv_harness/uvm_generator/templates/sim_scripts/validate_run_profile_args.py`**
   -- copied (not imported) into every generated environment. Deliberately
   **stdlib-only, zero dependency on the `dv_harness` package**: a
   delivered UVM environment ships to a DV team that does not necessarily
   have the Harness installed alongside it, so `just compile SPEED=gen1`
   must keep working from that tree alone. It duplicates the small
   enum/retired constraint check from `run_profile.py` on purpose -- this
   is the one place a little duplication is correct, because the two
   copies have genuinely different deployment/dependency contracts.

   A second lesson found the same way: `{{justfile_directory()}}`
   interpolated into a recipe body mangles under `set shell := ["bash",
   "-uc"]` on Windows (backslash-path characters get eaten). Fixed by using
   plain relative paths (`validate_run_profile_args.py`, `run_profile.json`)
   instead -- consistent with every other reference in the file, and
   correct because this justfile, like every other one this harness
   generates, is always invoked from its own directory.

## CLI

```
dv-harness run-profile extract --makefile <path> --out run_profile.json --target-ip USB --ip-prefix usb_
dv-harness run-profile justfile --profile run_profile.json --out justfile
```

## Tests

`dv_harness_tests/test_run_profile.py` (schema + query helpers),
`test_makefile_to_run_profile.py` (extraction asserted against the REAL
template Makefile's real variable names/enum values/plusarg bindings --
never a synthetic fixture, so a regression in the real file's own idioms is
caught), `test_run_profile_to_justfile.py` (generation, plus real `just`
subprocess execution when the `just` binary is present -- the two bugs
above are both regression-guarded here, not just fixed).

## Known scope limits (honest, not silently patched over)

- The extractor only recognizes the Make idioms actually observed in this
  project's own template Makefile. A materially different Makefile
  structure will simply produce a sparser (never a wrong) `run_profile.json`
  -- missing fields, not guessed ones.
- `command_txt` (an SoC-level SystemVerilog-task reference command.txt, as
  used in the live USB SYSTEM_LEVEL_MODE build) is in the schema's `source.kind`
  enum but has no extractor yet -- that source format is fundamentally
  different syntax (SystemVerilog tasks, not Make variable assignments) and
  needs its own extractor built against a real command.txt, not adapted by
  guesswork from this one.
- `mutual_requirement`/`forbidden_combination` constraints are captured in
  the schema shape but `check_constraints()` only evaluates
  `enum_membership` generically (re-implementing arbitrary Make-language
  conditional logic generically was judged not worth the complexity); a
  profile with such constraints still surfaces them for a human/agent to
  read, just not to auto-check.
