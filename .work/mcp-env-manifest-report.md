# env.manifest.json generator (Part A manifest half) -- implementation report

Scope: `dv_harness/env_manifest.py` and its supporting schemas/templates/CLI/tests
only. NOT built here (separate, parallel workstreams per the task's own scope
note): the read-only MCP server, the 3-tier ask-a-human question queue, and
bind-location/VIP-connectivity (that last one is real and landed concurrently
this session as `dv_harness/connectivity.py` -- see CLAUDE.md's new
"Bind-Location Rules (2026-09-03)" section and
`.work/mcp-bind-connectivity-report.md`).

## Files added

- `dv_harness/env_manifest.py` -- the generator itself.
- `dv_harness/schemas/env_manifest.schema.json` -- output schema (Draft 2020-12,
  same rigor/style as `dv_harness/uvm_generator/schemas/run_profile.schema.json`).
- `dv_harness/schemas/register_map.schema.json` -- the register-facts **input
  contract** (RAL/IP-XACT-modeled: name/address/width/fields/access).
- `dv_harness/uvm_generator/templates/uvm_env_manifest/dv_env_manifest_pkg.sv` --
  the generic, protocol-agnostic UVM template a generated environment includes
  to actually produce the vip_config and env_topology.component_hierarchy dumps.
  Static file, copied verbatim (same convention as
  `templates/sim_scripts/validate_run_profile_args.py`), never rendered through
  string substitution.
- `dv_harness_tests/test_env_manifest.py` -- 27 tests, all passing (see below).
- CLI: `dv-harness env-manifest generate --out <path> [--rtl-file ... (repeatable)]
  [--register-map ...] [--vip-config-dump ...] [--topology-dump ...]
  [--config-db-trace-log ...] [--verible-bin ...]`, wired into `dv_harness/cli.py`
  next to the existing `run-profile` subcommand, mirroring its pattern
  (validation-error-to-stderr-then-exit-1, JSON result to stdout).

## What's REAL (genuinely exercised against real tooling/data this session)

- **dut_facts.rtl**: extends `verible_parser.parse_file()`/`to_dict()`
  UNMODIFIED -- this module adds zero RTL-parsing logic of its own, only
  aggregation (sort-by-file_path for a stable diff) and manifest-shape
  wrapping. Verified against the REAL `verible-verilog-syntax` binary
  installed on this machine (`v0.0-4150-gfe58e708`), against a synthesized
  `fifo_ctrl` fixture -- module name, ports (direction/data_type), and
  parameters (type/default) all round-trip correctly. `VeribleUnavailableError`
  / `VeribleParseError` propagate straight through rather than being
  downgraded to NOT_AVAILABLE, since a real parse failure against a real
  supplied file is a real error, not "nothing was attempted."
- **dut_facts.registers**: `register_map.schema.json` is a real, validated
  JSON Schema (Draft 2020-12); `load_register_map()`/`build_dut_facts_registers()`
  genuinely load + jsonschema-validate a register-map JSON file and fold
  its `blocks` through unmodified. Tested against a synthesized fixture
  (clearly-fictional `TEST_CTRL_BLOCK`, never presented as real project
  content) including a malformed-hex-address rejection test.
- **vip_config / env_topology.component_hierarchy parsers**: real,
  schema-shape-checked JSON parsers (`parse_vip_config_dump()`,
  `parse_topology_dump()`) against the exact dump shape
  `dv_env_manifest_pkg.sv` actually writes (I hand-traced the SV
  `$fwrite`/JSON-building code against the Python parser's expectations
  field-by-field to keep the two in lockstep, then round-trip-tested both
  Python sides against synthesized fixture JSON matching that shape).
- **env_topology.config_db_trace**: the UVM_INFO report *envelope*
  (`UVM_INFO <file>(<line>) @ <time>: <reporter> [<id>] <message>`) is a
  genuinely well-documented, stable UVM format and is fully, correctly
  parsed and tested (including correctly ignoring unrelated UVM_INFO/
  UVM_ERROR lines). The message **body**'s internal field/value sub-format
  is explicitly, honestly NOT further decomposed -- kept as opaque raw text
  -- and flagged via a dedicated `parse_confidence:
  "envelope_verified_message_opaque"` field, since I do not have a live
  UVM run in this repo to verify that inner sub-format against (see Open
  Questions).
- **Determinism/diffability**: verified directly -- regenerating a manifest
  from unchanged real inputs twice produces byte-identical files
  (`test_regenerating_from_unchanged_inputs_is_byte_identical`), and there
  is no `generated_at`/timestamp field anywhere in the schema.
- **SV template syntax**: I do not have a licensed VCS/UVM install in this
  environment, so I cannot compile `dv_env_manifest_pkg.sv` end-to-end
  against a real UVM library. I DID run the real `verible-verilog-syntax`
  parser against it directly (rc=0, no errors) and confirmed the tool
  actually detects errors on this exact file by injecting one syntax fault
  and re-running (rc=1, correct error location reported) -- this catches
  gross syntax mistakes (mismatched braces/endclass/endfunction, malformed
  declarations) but does NOT prove UVM-macro/library-level correctness
  (e.g. that `uvm_component::get_children()`'s real signature matches what
  I wrote, that `` `uvm_error``/`` `uvm_info `` expand correctly). That
  remains genuinely unverified until run against a real UVM library.

## What's NOT_AVAILABLE-by-honest-design (never fabricated)

All three of vip_config, env_topology.component_hierarchy, and
env_topology.config_db_trace report `status: "NOT_AVAILABLE"` with a
non-empty, specific `reason` field when their real input artifact (a VIP
config dump, a topology dump, a +UVM_CONFIG_DB_TRACE sim log) does not
exist -- because no live UVM simv exists anywhere in `dv_harness` itself
(it is the meta-harness, not a generated project environment, exactly as
the task specified). Same for `dut_facts.registers` when no register-map
input file is supplied -- no live RAL model exists in this repo to read
from. `test_full_manifest_with_no_inputs_is_schema_valid_and_honestly_not_available`
and `test_full_manifest_never_fabricates_vip_or_topology_content_when_absent`
assert this explicitly: every NOT_AVAILABLE layer's `reason` is real,
non-trivial text (not merely a present-but-blank field), and every content
array (`vip_instances`, `components`, `entries`, `blocks`) stays genuinely
empty rather than carrying invented example content.

This mirrors the exact discipline `memory_vault.py`'s `ObsidianAdapter`
already established in this repo (per `docs/MEMORY_ARCHITECTURE.md`):
`installed`/`version` can be truthfully populated by a real probe, but a
capability nothing has actually exercised against real output stays
honestly `NOT_AVAILABLE`/`PARTIAL`, never silently upgraded to look more
complete than it is.

## Design decisions worth flagging

1. **Topology capture is a JSON walk of `uvm_top`'s real children, not a
   parser of `print_topology()`'s free-text table.** The task's spec names
   `uvm_top.print_topology()` as the mechanism; `dv_env_manifest_base_test`
   still calls the real `print_topology()` every run (so the human-readable
   table keeps landing in the sim log exactly where the spec's language
   points), but the manifest's own machine-readable input is a second,
   purpose-built dump this template also writes by walking `uvm_top` via
   `get_children()`/`get_full_name()`/`get_type_name()`/
   `uvm_agent::get_is_active()` -- stable UVM 1.2 API, not a documented text
   contract for `print_topology()`'s own table format (which varies by
   printer/UVM version and has never been observed live in this repo).
   Same "never guess a command contract" reasoning as `verible_parser.py`'s
   own module docstring. Flagged here explicitly as a disclosed deviation
   from literal spec wording, in service of the same spec's own honesty
   requirement.
2. **`vip_config` capture needs one line of integration per VIP config
   wrapper** (`dv_env_manifest_register_vip_config(instance_path, vip_type,
   field_names, field_values)`, called once each VIP's own config has
   resolved its real values). There is no cross-VIP-vendor API this
   package could call generically to enumerate "the VIP's own config
   object" -- that per-VIP resolution genuinely has to live in the
   generated environment, not in this generic template. A VIP wrapper that
   never calls it simply does not appear in the dump; the manifest reports
   that as a real, correctly-empty result, never fabricated.
3. **register_map.schema.json's `blocks` are only shallow-typed
   (`{"type": "object"}`) inside `env_manifest.schema.json` itself** and
   fully validated separately, up front, by `validate_register_map()`
   against the real `register_map.schema.json` (a stricter, per-field
   schema). Documented in `env_manifest.schema.json`'s own description so
   the two schemas cannot silently drift apart from each other while still
   both being schema-valid.

## Open questions (none blocking; none touch pass/fail verdicts)

- The exact literal internal sub-format of a real UVM 1.2
  `+UVM_CONFIG_DB_TRACE` message body (field name / context / value token
  layout) is unverified against a live run in this repo. Current design
  keeps it as opaque text rather than guessing a decomposition -- if/when a
  real sim log becomes available, `parse_config_db_trace_log()` should be
  re-checked against real output and, if the sub-format is confirmed
  stable, extended to decompose it into structured sub-fields.
- `dv_env_manifest_pkg.sv` is syntax-checked (verible) but not
  UVM-library-compiled (no VCS/UVM install in this environment) -- first
  real integration into a generated environment should confirm it compiles
  and actually produces both dump files end-to-end.

## Test run

```
python -m pytest dv_harness_tests/test_env_manifest.py -q
27 passed in 6.41s
```

Also re-ran `dv_harness_tests/test_verible_parser.py` and
`dv_harness_tests/test_makefile_to_run_profile.py` together (54 passed) to
confirm no regression from extending/depending on `verible_parser.py`, and
confirmed `python -m dv_harness --help` / `env-manifest --help` /
`env-manifest generate --help` all still parse correctly after the
`cli.py` edit (a `git diff dv_harness/cli.py` shows the edit is purely
additive -- zero removed lines -- alongside the sibling `exemptions`
subcommand block already present in the working tree from a concurrent
workstream, which was left untouched).

## Concurrency note

Per this session's explicit concurrency instructions, `dv_harness/cli.py`
is also being touched by the sibling "exemptions + harness reliability +
self-test CI" workstream. Before editing it I ran `git status --short` /
`git diff dv_harness/cli.py` to see its sibling hunk first, then made only
targeted `Edit` (diff-based) insertions at a different anchor point (right
after the existing `run-profile` subparser block, both for the argparse
definition and the dispatch branch) -- never a whole-file rewrite. No `git
add`/`git commit` was run by this task at all, specifically to avoid
sweeping the sibling's uncommitted hunks (also present in `config.py`,
`evidence_db.py`, `regression_reporter.py`, `test_evidence_db.py` per
`git status`) into a commit attributed to this task; committing is left to
whoever integrates all concurrent workstreams together.
