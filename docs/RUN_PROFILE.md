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

That paragraph is no longer prose an agent is trusted to have read: it is
parsed and compared, level for level, against `AUTHORITY_ORDER` in
`dv_harness/source_authority.py` (`assert_doc_matches_code()`, run by
`dv-harness authority check-doc` and by
`dv_harness_tests/test_source_authority.py`), so editing either side without
the other is a test failure. That module also owns `resolve_conflict()` --
which applies the order, including the "(DUT then Global)" sub-ordering
inside tier 4 -- and `escalate_conflict()`, which turns a disagreement the
order cannot settle into a real `question_queue` Tier-3 entry carrying both
sides' evidence paths. It is deliberately NOT the same list as
`tools/verification_flow/evidence_source_priority_gate.py`'s `ORDER`: that
one is a DISCOVERY order (which source to consult first for a fact you do not
have), this one is a CONFLICT order (which source wins when two you already
read disagree).

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
   operator reaching an unmodeled real target (e.g. `verdi`, `cov_gui`).
   Until 2026-09-04 it was restricted by a loud comment and nothing else, so
   at the point of invocation it was indistinguishable from a modeled recipe.
   It now takes an `ack` parameter ahead of the target and refuses anything
   but the literal `HUMAN_OVERRIDE_ACK_TOKEN`
   (`I-AM-A-HUMAN-BYPASSING-RUN-PROFILE`), whose refusal message names the
   question queue as the alternative. **Honest residual**: an agent can type
   that token. What is closed is a silent, deniable bypass -- the token
   appears verbatim in shell history and CI logs as an attributable claim.
   A deliberate bypass cannot be closed from inside a justfile.

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

6. **Source authority is verified, not asserted (2026-09-04).** The knob
   worth smuggling in was never in the generated justfile -- that file
   carries a "DO NOT hand-edit" banner and is regenerated anyway. It is in
   `run_profile.json`, which had no such check: an agent could add the param
   it wished existed and regenerate a perfectly valid justfile around it.
   `run_profile.assert_params_traceable_to_source()` re-reads the real
   Makefile / reference `command.txt` and refuses any param whose name does
   not appear in it as a whole token; `assert_source_unchanged()` refuses a
   profile whose recorded `source.content_sha256` no longer matches.
   `run_profile_to_justfile.verify_source_authority()` runs both before
   `generate_and_write()` emits anything, and is exposed as
   `python -m dv_harness.uvm_generator.run_profile_to_justfile verify-source
   <run_profile.json>` (exit 0 VERIFIED / 1 violation / 3 NOT_AVAILABLE).
   A profile inspected away from its environment reports NOT_AVAILABLE and
   still generates -- refusing there would be the false positive that gets
   the check routed around. The name-token check is deliberately not
   cleverer than that: parsing Make conditionals or SystemVerilog task
   bodies well enough to prove a param's *semantics* would be a second
   extractor, and a wrong one either rejects real params or accepts invented
   ones. A name absent from the authoritative source cannot have come from
   it, and that one claim is checkable with certainty.

7. **The question-queue route is a real code path (2026-09-04).** "A knob an
   agent believes is missing goes to the question queue" appeared in this
   document, in `run_profile.py`'s docstring, in the schema's own
   `description` and in the generated justfile's banner -- and in no code;
   `dv_harness/uvm_generator/` referenced `question_queue` nowhere.
   `run_profile_to_justfile.assert_option_modeled()` now refuses an
   unmodeled option as `UnmodeledOptionError`, and
   `build_missing_option_question_queue_entry()` asks it through the SAME
   `question_queue.QuestionQueueStore` that `connectivity.
   build_t4_question_queue_entry()` uses -- one queue for this harness, not
   a second parallel one. The record is owner-routed via `route_owner("env")`,
   id-derived (so regenerating does not mint a duplicate question), and
   carries `affects_pass_fail_verdict: True`, which classifies it Tier 3
   CANNOT_ASSUME: a silently-added execution knob does not produce a visibly
   broken run, it produces a PASS that verified something other than what
   was intended. Open-ended option lists and an already-modeled option are
   both refused.

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
above are both regression-guarded here, not just fixed), and
`test_four_key_judgments_enforcement.py` (the 2026-09-04 source-authority
and question-queue wiring: traceability against the REAL template Makefile,
a hand-added knob refused at `generate_and_write()` time with no justfile
written, whole-token matching, staleness, the NOT_AVAILABLE path, the CLI's
0/1/3 exit codes, a real persisted queue record with a stable derived id,
and the `human_raw_override` ack driven through the real `just` binary).

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
  guesswork from this one. **This is the one place the "reference source is
  the highest authority" rule is still only partly mechanical**: for a
  `command_txt`-sourced environment, `run_profile.json` is authored rather
  than extracted. Note the 2026-09-04 verification above does still apply to
  that case -- `assert_params_traceable_to_source()` reads whatever file
  `source.path` names, Makefile or command.txt, and a param absent from it
  is refused either way. So an authored profile is checked against its real
  source even though nothing yet derives it from one. Building the extractor
  is a separate effort: it needs a real SoC-level command.txt to be written
  against, and none is present in this repo.
- `mutual_requirement`/`forbidden_combination` constraints are captured in
  the schema shape but `check_constraints()` only evaluates
  `enum_membership` generically (re-implementing arbitrary Make-language
  conditional logic generically was judged not worth the complexity); a
  profile with such constraints still surfaces them for a human/agent to
  read, just not to auto-check.
