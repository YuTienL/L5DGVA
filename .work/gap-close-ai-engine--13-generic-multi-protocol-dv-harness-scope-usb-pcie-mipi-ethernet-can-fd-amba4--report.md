# Gap close: AI mechanism #13 -- Generic multi-protocol DV Harness scope

**Result: DONE** (for the one in-scope, fixable gap the audit named)
**Test summary**: 341 passed across `test_protocol_capability.py` + `test_qualification.py` +
`test_dashboard_interactive.py` + `test_engine_gates_and_routing.py` (exit 0), plus 104 passed
across the five protocol-model generator suites and 84 passed across the protocol/qualification
gate suites. New suite: 29 passed.

Date: 2026-09-04

---

## What was in scope and what was not

The audit's verdict was PARTIALLY_WIRED with **one concrete, checkable gap** named as fixable:

> `.dv-harness/qualification/protocol_capability_registry.json` asserts
> `"generation_capability": "REAL_CODE_GENERATOR_AVAILABLE"` for Ethernet, MIPI_CSI2, MIPI_DSI,
> SD_SDIO, eDP, UCIe -- none of which have a real protocol-specific `.py` generator.

That is what this pass closed. Everything else in the audit (a first non-USB DUT-proof pilot,
CSI-2/DSI packet layers, ACE-Lite/AXI-Stream, TLP/config-space) is a genuine separate build effort
and was **not** attempted -- see "Explicitly not done" below.

## Evidence re-verified before touching anything

Re-checked directly this pass, not taken from the audit text:

- `grep -rln "builder_profile" --include=*.py .` -> **empty**. The entire
  `.dv-harness/universal-protocol-platform/builders/` tree is inert metadata no Python reads.
  Confirmed.
- Real protocol-model generator modules present: `pcie_ltssm_generator.py`,
  `mipi_dphy_generator.py`, `canfd_arbitration_generator.py`, `amba_fabric_generator.py`,
  `emmc_cmdq_generator.py` -- **five**, plus the protocol-agnostic `protocol_env_generator.py`.
  No `ethernet_*.py`, no eDP module, no UCIe module.
- **Correction to the audit**: the audit treated the registry as a "status ledger". It is not
  inert. `dv_harness/dashboard.py:_protocol_registry()` reads it and renders it as the project's
  protocol readiness, and `_qualification_tier_reached()` derives the Qualification-Tiers card
  from it. The overstatement therefore reached a real production surface -- which raised the bar
  from "edit some JSON" to "wire the honest claim into the consumers".
- **Second overstatement source the audit did not name**: `.dv-harness/semantic-models/*.json`
  (10 files) carried the identical `"generation_capability": "REAL_CODE_GENERATOR_AVAILABLE"`.
  Zero Python consumers -- which is exactly why nobody noticed.
- **Third**: the registry's `new_interface_framework` block claimed the same
  `REAL_GENERATION_READY` for `VIP_ADAPTER`/`NATIVE_UVC`, while
  `grep -rn "NATIVE_UVC\|VIP_ADAPTER" --include=*.py .` returns nothing at all.
- Git status checked on every file before editing. `CLAUDE.md` was modified by a concurrent
  workstream mid-pass (an unrelated `memory_router.organizational_admission_gate()` paragraph), so
  it was edited by hand-scoped append against a unique tail anchor, never rewritten.

## The fix

The audit proposed splitting `generation_capability` into two honest fields and updating
`protocol_status.py`'s print format. Adjusted after being in the code: a hand-maintained pair of
fields is the same defect a year later. The claim is now **derived from code and enforced**.

### New: `dv_harness/protocol_capability.py`

Answers three separately-checkable questions instead of one collapsed label:

| question | how it is answered |
|---|---|
| generic skeleton available? | `protocol_env_generator`, verified importable. True for all 11 -- the true half of the old claim. |
| protocol's own behaviour modelled? | `PROTOCOL_CAPABILITIES` table; every module verified through `importlib.util.find_spec` and every standalone tool verified on disk before being reported. No module -> `NONE`, not talked up. |
| ever proven against a real DUT? | `dut_proof` paths that must EXIST. Only USB has any. |

- `derive_status()` computes `GENERIC_SKELETON_ONLY` / `PROTOCOL_MODEL_PARTIAL` /
  `PROTOCOL_MODEL_COMPLETE` / `DUT_PROVEN` from those facts.
- `assert_registry_matches_code()` raises `ProtocolCapabilityDriftError` (carrying **every**
  mismatch, not the first) on: a reintroduced `generation_capability` key, the retired
  `REAL_GENERATION_READY` status, the retired blanket per-entry note, any owned field disagreeing
  with the computation, a declared module that does not import, a declared tool or DUT-proof path
  that does not exist, a protocol missing from either side, or `new_interface_framework`
  reclaiming its old status.
- `--sync` regenerates the registry (and the 10 semantic-model files) from the code; `--check`
  exits 2 on drift.
- Harness assets (`tool`, `dut_proof`) resolve against `HARNESS_ROOT`, while the `root` argument
  selects which project's registry to read -- so a downstream project does not report every
  generator missing merely because its own tree has no `tools/`.
- `capability_status` shares no token with `qualification.py`'s 8-tier ladder, on purpose: PCIe
  has the deepest protocol model in the repo while sitting at `BUILDER_AVAILABLE`, which is why
  one field could never carry both questions.

### Wired into both real consumers

1. **`tools/universal_protocol/protocol_status.py`** -- now prints CAPABILITY and QUALIFICATION as
   separate columns plus the module name, and **refuses to print at all** (exit 2) when the
   registry claims more than the code backs. A status command that can print a stale overstatement
   is how this one survived.
2. **`dv_harness/dashboard.py`** -- `_protocol_registry()` carries `capability_status` and
   `protocol_model_generator`; the Protocols card renders both per tile (module name on hover,
   `cap-generic-only` / `cap-model` / `cap-dut-proven` CSS). Previously all 11 tiles read
   `BUILDER_AVAILABLE`, i.e. indistinguishable readiness. `qualification_status` is untouched.

### Data corrected

`.dv-harness/qualification/protocol_capability_registry.json` (regenerated, now self-describing as
generated), `.dv-harness/semantic-models/*.json` (10 files), `new_interface_framework`. Memory
records under `.dv-harness/memory/` are deliberately skipped by the legacy-claim scan -- they are
an append-only record of what was believed at the time; rewriting them would falsify it.

### Resulting honest state

| protocol | capability_status | protocol model generator |
|---|---|---|
| USB_2_3x | DUT_PROVEN | NONE (its proof is evidence artifacts, not a model module) |
| PCIe | PROTOCOL_MODEL_PARTIAL | `pcie_ltssm_generator` |
| MIPI_CSI2 / MIPI_DSI | PROTOCOL_MODEL_PARTIAL | `mipi_dphy_generator` (D-PHY layer only) |
| CAN_FD | PROTOCOL_MODEL_PARTIAL | `canfd_arbitration_generator` |
| AMBA4_MULTI_MASTER_MULTI_SLAVE | PROTOCOL_MODEL_PARTIAL | `amba_fabric_generator` |
| eMMC / SD_SDIO | PROTOCOL_MODEL_PARTIAL | `emmc_cmdq_generator` |
| **Ethernet / eDP_DisplayPort / UCIe** | **GENERIC_SKELETON_ONLY** | **NONE** |

Every PARTIAL entry names its unmodelled layers in `does_not_model` -- AMBA's
`ace_lite_coherency`/`axi_stream`, PCIe's `tlp_layer`/`config_space`, CSI-2's packet layer, and so
on. Partial-ness is data, not a footnote.

## Tests

`dv_harness_tests/test_protocol_capability.py` (29 tests). Deliberately about the **wiring**, since
"the underlying function works in isolation" was never the gap:

- the shipped registry is checked against the shipped code; every declared module really imports
  and every declared tool really exists
- a **negative control** proves an unmutated temp copy validates clean, so the drift tests below
  cannot pass for the wrong reason
- the original defect re-staged: Ethernet claiming `ethernet_mac_generator` is refused; so are a
  reintroduced `generation_capability`, the retired blanket status, an over-claimed
  `capability_status`, a dropped protocol, an unknown protocol, and `new_interface_framework`
  reclaiming its status -- and all problems are reported at once
- `--sync` is idempotent, repairs an overstated registry, and leaves fields owned by other
  mechanisms (`qualification_status`, `builder_profile`, `qualification_suite`) untouched
- **consumer 1**: `protocol_status.py` really prints both columns for the real registry and really
  exits 2 rather than reporting an overstated one
- **consumer 2**: a **real dashboard server** on a real port, real HTTP -- `/api/state` carries
  `capability_status`/`protocol_model_generator`, and the served HTML really renders the class with
  real CSS behind it
- DUT_PROVEN drops when its evidence path does not exist; the two vocabularies share no token

## Explicitly not done (NEEDS_SEPARATE_EFFORT, per task rule 3)

This closes the CLAIM, not the capability. No non-USB protocol became DUT-proven. A follow-up
effort should cover, in this order:

1. **PCIe as the bounded first non-USB pilot** -- still the right choice: RC/EP asymmetry reuses
   the proven `block/branch_a*/branch_fw/branch_b*` architecture directly (no new UNTESTED
   topology doc needed first, unlike AMBA-as-primary-DUT or CSI-2/DSI simplex streaming), and it
   is the only protocol with a generated example artifact. Scope: bind one real PCIe RTL DUT via
   `tools/generate_pcie_ltssm_environment.py`, run the 3 machine gates
   (`connectivity.run_machine_gates()`) against it, then extend past LTSSM into TLP/config-space.
2. **CSI-2 / DSI packet layers** (short/long packets, virtual channels, ECC/CRC) -- currently zero
   generator code; and validating the UNTESTED simplex-streaming `branch_fw` variant.
3. **Ethernet / eDP / UCIe protocol models** -- from zero.
4. **ACE-Lite and AXI-Stream** -- AXI-Stream has no address channel, so it is structurally out of
   reach of an address-decode fabric generator and needs its own model, not an extension.
5. **Making the `universal-protocol-platform/builders/` tree real** -- today no Python reads any
   `builder_profile.json`. Either wire it into generation or retire it; leaving inert metadata that
   looks authoritative is how this finding happened.

## Files changed

- `dv_harness/protocol_capability.py` (new)
- `dv_harness_tests/test_protocol_capability.py` (new)
- `tools/universal_protocol/protocol_status.py`
- `dv_harness/dashboard.py`
- `.dv-harness/qualification/protocol_capability_registry.json`
- `.dv-harness/semantic-models/*.json` (10 files)
- `CLAUDE.md` -- new "Per-Protocol Capability: Two Questions, Never One Label (2026-09-04)"
  section (hand-scoped append; the file was concurrently edited mid-pass)
