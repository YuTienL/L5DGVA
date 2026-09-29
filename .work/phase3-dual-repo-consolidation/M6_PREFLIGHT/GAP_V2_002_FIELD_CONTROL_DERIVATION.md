# GAP-V2-002 Remediation — FieldControl Derivation

Per `DEC-GAP-V2-002 = OPTION_B`'s own instruction: "Do not assume the final
FieldControl set. Derive it from all 11 PROTOCOL_BUILDERS and actual
downstream generation consumers." This document is that derivation, real
evidence first, never assumed.

## Method

1. Extracted every one of the 11 `.claude/skills/PROTOCOL_BUILDERS/*/
   SKILL.md`'s own `## Discover Before Generate` section verbatim (11
   short bullet lists — the minimum, complete input).
2. Read every downstream generation consumer's own manifest-key usage
   directly: `dv_harness/uvm_generator/generator.py`,
   `protocol_env_generator.py`, `protocol_model_layer.py`,
   `create_environment.py` (`grep -n "m.get(\|manifest.get("` across all
   four, then read each real hit in context).
3. Classified every field named in step 1 against what step 2 actually
   found consumed — never against what the prose merely asked an agent to
   discover.

## The 11 skills' own "Discover Before Generate" lists (verbatim)

| Skill | List |
|---|---|
| amba4-soc | AXI3/AXI4/AXI4-Lite/AXI-Stream/AHB/AHB-Lite/APB3/APB4; master/slave topology; address map; ID namespace; clock/reset domains |
| canfd | node/controller role; Classical CAN/CAN-FD; ISO/non-ISO; nominal/data bit timing |
| edp | source/sink role; link rate; lane count; AUX/DPCD; eDP/DP feature set |
| emmc | host/device role; bus width; timing modes; HS200/HS400 capability; partition/features |
| ethernet | MAC/PCS/PMA boundary; speed/mode; GMII/XGMII/USXGMII/SXGMII; 10G/25G and project modes |
| mipi-csi | TX/RX role; CSI-2 version; C-PHY/D-PHY; lane count; VC/DT usage |
| mipi-dsi | Host/Peripheral role; Video/Command mode; C-PHY/D-PHY; lane count; VC/DT/DCS usage |
| pcie | RC/EP/Switch role; Gen2-Gen6; lane width; Serial/PIPE/controller boundary |
| sd | host/card role; SD/SDHC/SDXC/SDIO; bus width; speed/UHS modes |
| ucie | die/adapter role; UCIe version; PHY/adapter/protocol boundary; lane/module topology |
| usb | Host/Device role; USB2/USB3 mode; port topology; PHY/controller boundary |

## Downstream consumer evidence (what is actually read, confirmed by direct read)

```
generator.py:431   m.get('role', 'UNKNOWN')     -- read into generated UVM
                    code, real default; reused unchanged by
                    ProtocolEnvGenerator (protocol_env_generator.py's own
                    module docstring: "reuses this module's per-class emit
                    methods unchanged")
protocol_model_layer.py:96   TOPOLOGY_KEY = "protocol_model_topology"
                    -- a nested, PROTOCOL-SPECIFIC dict (PCIe's own shape:
                    name/lane_width/gen_speed/role/ltssm_state_signal),
                    OPTIONAL, read only for the 5 protocols with a real
                    protocol_model (PCIe LTSSM, MIPI D-PHY, CAN-FD
                    arbitration, AMBA fabric, eMMC/SD command queue)
create_environment.py   request["protocol"] / _requested_subsystems()
                    -- already governed (CAP-M6-C1-001)
```

No generator anywhere reads a bare, flat `mode` or `topology` key. No
generator reads `phy_boundary`/`dut_boundary` at all.

## Classification (every discovered field, one of the 6 required categories)

| Field | Classification | Evidence |
|---|---|---|
| `protocol` | `EXISTING_CANONICAL_FIELD` | Built by `CAP-M6-C1-001`; `create_environment()`'s own `request["protocol"]` |
| `role` (host/device, RC/EP/Switch, TX/RX, source/sink, master/slave, node/controller, die/adapter, Host/Peripheral) | `NEW_GENERIC_CANONICAL_FIELD` | Real, actually-consumed key (`generator.py:431`), present under some name in ALL 11 skills' own discover list -- protocol-specific vocabulary, generic slot, same precedent as `protocol` itself. Built this task: `generation_field_controls.role_field_control()`. |
| `mode`/protocol version (USB2/USB3, Gen2-Gen6, CSI-2 version, Video/Command mode, Classical/CAN-FD, SD/SDHC/SDXC/SDIO, AXI3/AXI4/..., UCIe version, timing modes, speed/mode, link rate) | `PROTOCOL_SPECIFIC_EXTENSION` | Real per-skill discovery item, but no generic flat key is ever read by any generator; each protocol's own real shape differs completely (e.g. PCIe's `gen_speed` lives inside the OPTIONAL, protocol-specific `protocol_model_topology` dict, not a top-level field). Stays inside the caller-supplied `generation_request` manifest content, same as `clocks`/`resets`/`smoke_tests` already do -- never forced into one generic FieldControl, which would misrepresent a genuinely protocol-specific shape as a generic one. |
| `topology` (master/slave topology, port topology, lane/module topology, lane count/width, bus width, AUX/DPCD, VC/DT usage, ID namespace, address map, clock/reset domains) | `PROTOCOL_SPECIFIC_EXTENSION` | Same reasoning as `mode` -- the one real structured topology concept in the codebase (`protocol_model_layer.TOPOLOGY_KEY`) is itself protocol-specific and optional, used by only 5 of 11 protocols. |
| `phy_boundary`/`PHY-controller boundary` (USB, PCIe, Ethernet, MIPI CSI/DSI, UCIe) | `EXISTING_CANONICAL_FIELD`, but `NOT_ACTUALLY_REQUIRED` **for this generation path specifically** | Already has a real Canonical producer (`phy_boundary.py`, joined by `intake_state.py`'s own `dut_boundary` category) -- but neither `create_environment()` nor `ProtocolEnvGenerator` reads a `phy_boundary`/`dut_boundary` key; the real consumer is the SEPARATE bind-generation tool (`bind_mechanism_generator.py`/`tools/generate_bind_mechanism.py`). Wiring it into `generation_field_controls.py` would misrepresent which tool actually uses it -- not built here. |
| `verification_level` | `EXISTING_CANONICAL_FIELD`, deliberately `NOT_ACTUALLY_REQUIRED` for THIS task | `lifecycle._FACT_KEYS` already reserves it; resolving it through Field Resolution is `CAP-M5M6-VLEVEL-001`'s own explicitly separate, not-yet-authorized scope -- out of bounds here by the same standing rule `CAP-M6-DISPATCH-001`/`CAP-M6-C1-001` both already respected. Investigated per the dispatch's own explicit "at minimum investigate" instruction; not implemented. |
| Everything else in the 11 lists (address map, ID namespace, clock/reset domains, AUX/DPCD, VC/DT/DCS usage, HS200/HS400 capability, partition/features, timing modes, bit timing, ISO/non-ISO, ...) | `DERIVED_VALUE` or `EVIDENCE_ONLY` | Real content an agent must still gather from current DUT/spec/VIP evidence and place into the `generation_request` manifest -- this is exactly the domain the "No Golden-Reference Content Mining" rule and the VIP-scenario-branch skill already govern; none of it is a generic intake SLOT a Field Resolution question can meaningfully ask about in isolation (the answer's own correctness depends on real DUT/spec evidence, not a human's one-line confirmation the way `protocol`/`role` do). |

## Result

Two, and only two, fields governed by `generation_field_controls.py`:
`protocol` (already real, `CAP-M6-C1-001`) and `role` (new this task). Every
other field investigated has a real, evidence-based reason it is NOT one
more `FieldControl` in this module -- either it already has a different
real Canonical producer serving a different consumer (`phy_boundary`), it
is out of this task's authorized scope (`verification_level`), or it is
genuinely protocol-specific/content-shaped rather than a generic intake
slot (`mode`/`topology`/everything else). No second Field Resolution
engine was created for any of them.
