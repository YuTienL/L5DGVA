# Gap close: AI mechanism #13 -- Generic multi-protocol DV Harness scope (USB/PCIe/MIPI/Ethernet/CAN-FD/AMBA4)

**Verdict: DONE**

*Supersedes the earlier report at this same path (commit 7af2040), which covered the previous pass
on this mechanism -- splitting the collapsed per-protocol capability CLAIM. That pass's content is
preserved in git history and summarised in CLAUDE.md's "Per-Protocol Capability" section; this pass
closes the WIRING gap that one explicitly left open.*

**One-line test summary**: `dv_harness_tests/test_protocol_model_layer_wiring.py` -- 33 passed
(new); regression set `test_protocol_capability.py` + `test_system_level_soc_composition_wiring.py`
+ `test_protocol_env_generator.py` + `test_protocol_router.py` -- 70 passed; the five protocol-model
unit suites + `test_state_machine_checks.py` + `test_generator_wiring_notices.py` +
`test_generate_observability_plan_assertions.py` -- 134 passed.

---

## What the gap actually was (re-verified in the code, not restated from the audit)

The audit's verdict PARTIALLY_WIRED was correct, and its named cause was the right one. Re-checked
before touching anything:

```
$ grep -rn "pcie_ltssm_generator\|canfd_arbitration_generator\|mipi_dphy_generator\|
           emmc_cmdq_generator\|amba_fabric_generator" --include=*.py .   # minus tests/pycache
```

Every non-test caller of the five protocol-model generators was that model's own standalone
`tools/generate_*.py` script (plus `amba_fabric_generator.parse_addr`, imported by
`address_map_verifier.py` for address parsing only -- not for generation).
`dv_harness/uvm_generator/create_environment.py` -- the CREATE ENVIRONMENT entry point
`tools/generate_protocol_uvm_environment.py` calls, and the script every
`.claude/skills/PROTOCOL_BUILDERS/*/SKILL.md` invokes -- imported none of them. Its SUBSYSTEM_MODE
branch was one unconditional line:

```python
generated = ProtocolEnvGenerator(out_dir).generate(manifest)
```

So a manifest carrying `protocol: "PCIe"` produced byte-for-byte the same protocol-agnostic
skeleton a manifest carrying `protocol: "Ethernet"` produced. The LTSSM model's unit tests passed
the whole time while the production path never called it -- the exact PARTIALLY_WIRED shape this
audit hunts.

Everything else the audit found real, I found real: `protocol_capability.py` is genuine and
self-checking (`--check` exits 0), `protocol_router.py` covers all 9 protocols, the five models are
non-trivial math, `state_machine_checks.py` really does generalize the PCIe legality pattern into a
manifest-driven DSL that `generator.assertions()` already consumes. Nothing needed to be built from
scratch; the missing thing was a wire between pieces that all already existed.

Out of scope by the task's own framing and left alone: proving any non-USB protocol against a real
DUT, and the two UNTESTED non-USB topology variants (CSI-2/DSI simplex streaming,
AMBA-as-primary-DUT).

## What changed

### New: `dv_harness/uvm_generator/protocol_model_layer.py`

The wire. Reuses the three mechanisms that already exist rather than adding a parallel one:

- **Which module implements a protocol** comes from
  `protocol_capability.PROTOCOL_CAPABILITIES` -- already the single code-derived answer to that
  question, already drift-checked by `--check`. No second table.
- **How it is invoked** is that entry's `generator_class`, resolved through the import system by
  the new `protocol_capability.resolve_generator_class()`.
- **What it is invoked with** is the manifest's new `protocol_model_topology` key: that model's own
  topology schema verbatim (the identical dict its standalone tool takes). Each generator's own
  typed validator judges it; nothing is re-validated or defaulted here.
- **Protocol resolution** goes through `capability_for()` (now case-insensitive, plus the
  router-canonical `amba`/`canfd`/`sdio` aliases) and then `protocol_router.resolve_protocol()`, so
  the registry's `PCIe`/`eMMC` casing, the router's lowercase canon and a hand-written
  `PCI Express` all land on the same entry instead of silently reporting a modelled protocol as
  unmodelled.

Three deliberate properties:

1. **The model reaches the MAIN environment, not just a side directory.** Emitting
   `protocol_model/*.sv` alone would leave the generated testbench unchanged. Where a model exposes
   a state graph (today PCIe's `LTSSM_TRANSITIONS`) and the manifest names the real DUT signal
   carrying that state, the graph is compiled into a `state_machine_checks` entry -- the EXISTING
   DSL `generator.assertions()` consumes, whose own docstring says it generalizes precisely
   `pcie_ltssm_generator`'s hardcoded LTSSM-legality pattern -- so real transition-legality SVA
   lands in `tb/env/<p>_assertions.sv`, typed against the package the same run layered. The model's
   `.sv` files are PREPENDED to the environment filelist (a package must compile before the file
   typed against it), in the order the model's own `filelist.f` declares.
2. **Nothing is defaulted; no absence is silent.** `lane_width`/`gen_speed`/`role` and a state-signal
   name are DUT facts. A manifest without them still generates, but the environment's own
   `environment_manifest.json` carries a `protocol_model` record saying
   `PROTOCOL_MODEL_TOPOLOGY_NOT_SUPPLIED` and naming the module that would have run -- the same
   honesty contract `protocol_capability.py` enforces on the registry, applied per generated
   environment. Missing state signal -> the model still layers, but no assertion is emitted against
   a signal nobody confirmed, and the refusal is recorded.
3. **A rejected topology refuses.** A supplied-but-invalid topology raises
   `ProtocolModelLayerError` carrying the model's own `reason`/`detail` (e.g. `INVALID_LANE_WIDTH`
   for a PCIe x3), rather than handing back a skeleton the caller reads as the modelled environment
   they asked for. Same posture as `create_environment.py`'s existing `SubsystemModeRequiredError`.

### Modified

- **`dv_harness/uvm_generator/create_environment.py`** -- SUBSYSTEM_MODE now plans the model,
  injects the state-machine check, records the plan into the manifest (so it reaches the generated
  `environment_manifest.json`), generates the skeleton, then emits the model's files. Returns
  `protocol_model` and `protocol_model_files`.
- **`dv_harness/protocol_capability.py`** -- `ProtocolModel` gains `generator_class` (declared with
  the module so there is one place saying which module implements a protocol and how it is called);
  `resolve_generator_class()`; `capability_for()` case-insensitive fallback + `amba`/`canfd`/`sdio`
  aliases; `assert_registry_matches_code()` now resolves the declared class for real, so a renamed
  class fails `--check` instead of a generation run. PCIe's `capability_note` corrected -- it said
  "Reachable only via the standalone tool, not from engine.py/cli.py", which this change makes
  false. Registry re-synced (`--sync`; one entry changed, `--check` exits 0).
- **`tools/generate_protocol_uvm_environment.py`** -- reports the `protocol_model` block in its JSON
  output and exits 4 on `ProtocolModelLayerError`, so the status is visible at the entry point and
  not only inside the generated manifest.
- **`CLAUDE.md`** -- "Per-Protocol Capability" section gains the wiring paragraph; its scope boundary
  now reads "this closes the CLAIM and the WIRING, not the capability".
- **`.claude/skills/PROTOCOL_BUILDERS/pcie-environment-builder/SKILL.md`** -- the concrete
  `protocol_model_topology` block, what each field is evidence for, and what happens when it is
  omitted. **`amba4-soc-environment-builder/SKILL.md`** -- same topology now usable in-manifest.
  Both synced to `industrial/` and `PACKAGE/` per the Methodology Consolidation Rule.

## Proof that the WIRING is what is tested (not the models in isolation)

`dv_harness_tests/test_protocol_model_layer_wiring.py`, 33 tests, every one driving the real
`create_environment()` entry point:

- the LTSSM package/state-register really appear in the generated environment for a PCIe manifest;
- the emitted SV carries the real `LTSSM_TRANSITIONS` table, asserted state by state against the
  live Python table (not a golden string);
- **byte-comparison against the standalone tool's own `PCIeLTSSMGenerator(out).generate(topology)`**
  -- this is the test that fails if anyone ever "wires in" a protocol model by reimplementing its
  output inside the generation path instead of calling it;
- the model reaches `tb/env/pcie_assertions.sv` with the real DUT signal and the layered package's
  enum type;
- filelist compile order (package before the file typed against it, before the skeleton);
- **USB stays byte-identical** in every generated SV file (the only difference anywhere is the
  honest `protocol_model` record in `environment_manifest.json`);
- missing topology / missing state signal / a hand-written check of the same name / a rejected
  topology -- each recorded or refused, never silent;
- all five protocol-model modules layer through the entry point (parametrized over CAN_FD,
  MIPI_CSI2, MIPI_DSI, AMBA4, eMMC, SD_SDIO) -- PCIe is the recommended first pilot, not a special
  case in the code;
- Ethernet / an unknown protocol claim nothing;
- 13 manifest protocol spellings resolve to the right capability entry;
- every declared `generator_class` resolves and has `generate()`;
- this repo's shipped registry still matches the code.

## What this does NOT close (stated so it is not read as more)

- **No non-USB protocol is proven against a real DUT.** The layered output has still never been
  compiled or bound. Steps 2 and 3 of the audit's own fix plan (bind a real PCIe RTL DUT, run
  `connectivity.py`'s 3 machine gates against it; extend `pcie_ltssm_generator` past LTSSM into
  `tlp_layer`/`config_space`) are untouched and remain the real remaining PCIe gap. Step 4
  (`dut_proof` paths) is deliberately untouched: PCIe has no DUT evidence to point at, and pointing
  the field at a path that is not there is what the registry's drift guard exists to catch.
- The two UNTESTED non-USB topology variants (CSI-2/DSI simplex streaming, AMBA-as-primary-DUT) are
  unchanged -- they are documentation for a future pilot, and this pass built no pilot.
- Ethernet/eDP/UCIe gained nothing protocol-specific, because nothing protocol-specific exists for
  them; they now say so per generated environment instead of only in the registry.

## Commit

Single scoped commit; see the repository log.
