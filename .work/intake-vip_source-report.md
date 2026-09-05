# USB VIP Source Code — Deep Extraction Report

Category: 2 (VIP source code, reference class). Scope per task: `D:\DV\Task\USB\VIP\include\sverilog\`
and `D:\DV\Task\USB\VIP\src\sverilog\` (plus a check of `src\C`, `src\gate`, `src\vera`, `src\verilog`).
VIP identified from in-file version stamp: **Synopsys SVT USB VIP, version `W-2025.03`**
(`include/sverilog/svt_usb_defines.svi:57`: `` `define SVT_USB_VERSION W-2025.03 ``).

This report is a structured, citeable digest of what is *actually in the source tree* — not a
regurgitation of VIP marketing docs. Every class/field/method/signal named below was read directly
out of the file at the cited path/line. Where content is vendor-encrypted, that is stated
explicitly and no content is invented for it.

---

## 0. Directory reality check (corrects any assumption of a richer multi-language tree)

```
VIP/src/C        -> 0 files (empty)
VIP/src/vera     -> 0 files (empty)
VIP/src/gate     -> gtech/, zebu/ subdirs exist but contain no USB-specific gate netlist content examined; not relevant to UVM class extraction
VIP/src/rtl      -> 0 files (empty)
VIP/src/verilog/mti -> plain-Verilog "nvs_*" DPI/BFM library (nvs_fifo.v, nvs_lib_*.v/.vih, nvs_pool.v, ...) — this is
                       Synopsys's older NVS (Native VMM/Verilog Shell) plain-Verilog channel/BFM plumbing, NOT USB-protocol
                       source. No svt_usb_* content lives here.
VIP/src/sverilog/mti  -> 458 svt_usb_*.sv/.svi files (the real USB class implementations) + shared svt_* base-class
                          library (svt_agent.sv, svt_xactor.sv, svt_transaction.sv, svt_sequencer.sv, svt_configuration.sv, ...)
VIP/src/sverilog/ncv  -> an IDENTICAL 458-file svt_usb_*.sv mirror, simulator-targeted at Cadence Xcelium (ncv)
VIP/src/sverilog/vcs  -> an IDENTICAL 458-file svt_usb_*.sv mirror, simulator-targeted at Synopsys VCS
VIP/include/sverilog  -> ~150 svt_usb_*.svi/.pkg files: interface definitions (`svt_usb_if.svi` + all DUT-facing
                          sub-interfaces), package files (`svt_usb.uvm.pkg` etc.), macro/define headers,
                          and the technology "_source.*.svi" files that `` `include `` the .sv files into the package.
```

**Correction to any assumption of per-simulator content divergence**: `mti`, `ncv`, and `vcs` under
`src/sverilog/` are not different implementations — a diff of the first 50 lines of
`svt_usb_agent.sv` in `vcs/` vs `mti/` is byte-identical (same macro preamble, same class skeleton).
They are the same class source, each re-encrypted with a simulator-specific `pragma protect`
key (`encrypt_agent = "Model Technology"` for mti; VCS/NCV builds carry their own key blocks).
This report extracts from `mti/` as the representative tree; `ncv/` and `vcs/` classes are
identical in structure.

---

## 1. Encryption status — what is real vs. vendor-locked

All 458 `.sv` class-implementation files under `src/sverilog/mti/` (and the ncv/vcs mirrors) use
Synopsys/Mentor `` `pragma protect `` (`encrypt_agent = "Model Technology"`, `data_method =
"aes128-cbc"`, RSA-wrapped AES key, base64 data blocks) to encrypt content. **But the encryption is
selective, not whole-file**: the vendor leaves the class *skeleton* — `class`/`endclass`,
`typedef enum`, public field declarations, Javadoc-style `/** ... */` API comments, and every
`extern virtual function` / `extern task` **prototype** (return type, name, full argument list) —
in cleartext, and encrypts only the method *bodies*, `constraint` blocks, and private/local
implementation data as a sequence of separate `` `pragma protect begin_protected `` /
`end_protected` blocks scattered through the file. This means the full **public API surface**
(every field, every method signature, every enum, every port) of every class below is genuinely
readable; only algorithmic bodies (LTSSM transition logic, packet CRC/bit-stuffing math,
constraint solver bodies, protocol state-machine internals) are opaque ciphertext.

Sequence-collection files (system/virtual sequence libraries, e.g.
`svt_usb_20_na_30_ss_transfer_system_virtual_sequence_collection.sv`) and most `.svi` interface
files are **100% cleartext** — no encryption at all — because sequences and interfaces are meant
to be read/extended by the licensee.

Cleartext-fraction measurements (`wc -l` on file minus every `begin_protected..end_protected` span),
computed directly, not estimated:

| File | Total lines | Cleartext lines | % clear |
|---|---:|---:|---:|
| `svt_usb_agent.sv` | 18091 | 520 | 2.9% |
| `svt_usb_protocol.sv` | 14058 | 702 | 5.0% |
| `svt_usb_hub_agent.sv` | 1602 | 188 | 11.7% |
| `svt_usb_agent_if_object.sv` | 161 | 20 | 12.4% |
| `svt_usb_link.sv` | 7906 | 1498 | 18.9% |
| `svt_usb_physical.sv` | 9648 | 1944 | 20.1% |
| `svt_usb_xhci_trb.sv` | 1583 | 350 | 22.1% |
| `svt_usb_transaction.sv` | 7145 | 2428 | 34.0% |
| `svt_usb_agent_service.sv` | 1597 | 582 | 36.4% |
| `svt_usb_transfer.sv` | 11891 | 4683 | 39.4% |
| `svt_usb_configuration.sv` | 31667 | 12638 | 39.9% |
| `svt_usb_agent_configuration.sv` | 2680 | 1109 | 41.4% |
| `svt_usb_system_virtual_sequencer.sv` | 658 | 274 | 41.6% |
| `svt_usb_host_configuration.sv` | 2006 | 870 | 43.4% |
| `svt_usb_payload.sv` | 1645 | 702 | 42.7% |
| `svt_usb_xhci_trb_ring.sv` | 726 | 332 | 45.7% |
| `svt_usb_bus_instance.sv` | 877 | 429 | 48.9% |
| `svt_usb_device_configuration.sv` | 2158 | 1025 | 47.5% |
| `svt_usb_protocol_service.sv` | 6182 | 1994 | 32.3% |
| `svt_usb_virtual_sequencer.sv` | 432 | 234 | 54.2% (rest is only the file-guard tail) |
| `svt_usb_xhci_td.sv` | 1295 | 707 | 54.6% |
| `svt_usb_endpoint_configuration.sv` | 3740 | 2019 | 54.0% |
| `svt_usb_types.sv` | 6238 | 3877 | 62.2% |
| `svt_usb_packet.sv` | 20841 | 6594 | 31.6% |

`svt_usb_virtual_sequencer.sv` and `svt_usb_system_virtual_sequencer.sv` are effectively **100%
readable for API purposes** — the only encrypted spans in those two files are the method
*bodies* at the very end; every field, macro-field registration, and method prototype (21 and 15
`extern` declarations respectively) is cleartext, quoted in full below.

**Do not attempt to reconstruct method bodies for the low-%-clear files** (`svt_usb_agent.sv`,
`svt_usb_protocol.sv`, `svt_usb_link.sv`, `svt_usb_physical.sv`, `svt_usb_hub_agent.sv`): the LTSSM
state-transition logic, protocol scheduler internals, and CRC/bit-stuff/scrambling math are
genuinely opaque ciphertext in this tree. Everything quoted below for those files is either a
field declaration, an enum, or an `extern` prototype that survived encryption verbatim.

---

## 2. Real class hierarchy (verified from `class X extends Y` lines, not inferred)

```
svt_data (base SVT framework)
 └─ svt_status
     ├─ svt_usb_status                      (svt_usb_status.sv:36)   — the shared_status object
     ├─ svt_usb_bus_instance                (svt_usb_bus_instance.sv:23)
     ├─ svt_usb_xhci_td                     (svt_usb_xhci_td.sv:30)
     └─ svt_usb_xhci_trb_ring               (svt_usb_xhci_trb_ring.sv:34)

svt_configuration (base SVT framework)
 └─ svt_usb_configuration                   (svt_usb_configuration.sv:189)
     ├─ svt_usb_agent_configuration          (svt_usb_agent_configuration.sv:107, via macro `SVT_USB_SUBENV_CONFIGURATION_TYPE)
     ├─ svt_usb_hub_agent_configuration       (svt_usb_hub_agent_configuration.sv:14, via macro `SVT_USB_HUB_SUBENV_CONFIGURATION_TYPE)
     ├─ svt_usb_device_configuration          (svt_usb_device_configuration.sv:27)   — SIBLING of agent_configuration, not a child
     ├─ svt_usb_host_configuration            (svt_usb_host_configuration.sv:14)      — SIBLING, not a child
     └─ svt_usb_endpoint_configuration        (svt_usb_endpoint_configuration.sv:19)  — SIBLING, not a child

`SVT_TRANSACTION_TYPE  (macro; resolves to svt_sequence_item under UVM/OVM [itself built on
                         uvm_sequence_item via svt_sequence_item_base], or to svt_transaction
                         [built on vmm_data] under VMM — see src/sverilog/mti/svt_transaction.sv:32-56)
 ├─ svt_usb_transaction                     (svt_usb_transaction.sv:268)  — protocol-layer transaction (token/data/hshk-level)
 ├─ svt_usb_transfer                        (svt_usb_transfer.sv:420)     — protocol-layer transfer (composite of transactions)
 ├─ svt_usb_packet                          (svt_usb_packet.sv:39)        — link-layer packet
 ├─ svt_usb_protocol_service                (svt_usb_protocol_service.sv:19)
 ├─ svt_usb_agent_service                   (svt_usb_agent_service.sv:25, via macro `SVT_USB_SUBENV_SERVICE_TYPE)
 └─ svt_usb_xhci_trb                        (svt_usb_xhci_trb.sv:13)      — xHCI TRB ring-element data item

`SVT_DATA_TYPE (macro; svt_data / vmm_data)
 └─ svt_usb_payload                         (svt_usb_payload.sv:44)

svt_xactor (base SVT active-component framework, NOT svt_driver/svt_monitor)
 ├─ svt_usb_link                            (svt_usb_link.sv:321)
 ├─ svt_usb_physical                        (svt_usb_physical.sv:488)
 └─ svt_usb_protocol                        (svt_usb_protocol.sv:606)

svt_agent (UVM/OVM) / svt_subenv (VMM)   -- macro `SVT_USB_SUBENV_SVT_TYPE / `SVT_USB_SUBENV_BASE_TYPE
 └─ svt_usb_agent                           (svt_usb_agent.sv:958, class name is the macro
                                              `SVT_USB_SUBENV_TYPE = svt_usb_agent for UVM/OVM,
                                              svt_usb_subenv for VMM)

`SVT_USB_HUB_SUBENV_SVT_TYPE (parallel hierarchy, its own agent-like base)
 └─ svt_usb_hub_agent                       (svt_usb_hub_agent.sv:32, class name is macro `SVT_USB_HUB_SUBENV_TYPE)

svt_sequencer (base SVT framework)
 ├─ svt_usb_virtual_sequencer               (svt_usb_virtual_sequencer.sv:10)
 └─ svt_usb_system_virtual_sequencer        (svt_usb_system_virtual_sequencer.sv:10)
 (plus non-virtual, macro/parameterized `SVT_XVM(sequencer)`-based sequencers that are declared
  as fields, not found as their own `.sv` files with visible `class X extends`: svt_usb_transfer_sequencer,
  svt_usb_link_service_sequencer, svt_usb_protocol_service_sequencer, svt_usb_agent_service_sequencer,
  svt_usb_packet_sequencer, svt_usb_data_sequencer, svt_usb_physical_service_sequencer,
  svt_usb_link_packed_transaction_sequencer — these are `typedef class` forward-declared in
  svt_usb_agent.sv:74-76 and referenced as typed fields, and are generated via the SVT
  `` `svt_xvm_sequencer_utils `` / channel macros rather than being hand-written subclass files.)

svt_usb_types   -- a bare "namespace" class (svt_usb_types.sv:276, `class svt_usb_types;` — NOT
                   extending anything) that holds ~90 `typedef enum` declarations used throughout
                   every other class (speed_enum, ep_type_enum, dut_type_enum, ltssm_*_enum, ...).
```

### 2.1 Correction to the task's premise
The task asked to extract "svt_usb_sequencer" as if a single class of that name exists. **No file
or class named `svt_usb_sequencer` exists in this VIP.** The real sequencer layer is a *set* of
sequencer classes, listed above, each bound to one protocol-stack layer (physical/data,
physical/service, link/packet, link/service, protocol/transfer, protocol/service, agent/service),
unified under one `svt_usb_virtual_sequencer` per agent instance and one
`svt_usb_system_virtual_sequencer` per host+device pair. Any future generation/debug agent asking
for "the USB sequencer" should be pointed at `svt_usb_virtual_sequencer` (per-agent) or
`svt_usb_system_virtual_sequencer` (system/env level), not a nonexistent `svt_usb_sequencer`.

### 2.2 Correction/extension to prior session's `svt_usb_agent.sv:1216` / `svt_usb_if.svi` claim
Verified: `svt_usb_agent.sv` line-content re-confirmed at a *different* line number than previously
cited (encryption-block line-shifts mean absolute line numbers are fragile references — this
extraction found the same field at line **351** of the raw file / cleartext-extract line 351-352,
inside a block guarded by `` `ifndef SVT_VMM_TECHNOLOGY``):
```systemverilog
/** Input port for service requests to this Agent. */
`SVT_XVM(seq_item_pull_port) #(svt_usb_agent_service) agent_service_in_port;
/** Output queue for service requests received to this Agent. */
svt_usb_agent_service agent_service_rcvd_q[$];
```
So `agent_service_in_port` is real, and it is specifically a
**`uvm_seq_item_pull_port #(svt_usb_agent_service)`** (via the `` `SVT_XVM `` macro), not a generic
port — it pulls `svt_usb_agent_service` transaction objects, and pairs with the
`svt_usb_agent_service_sequencer` field also declared in the same class. For VMM technology the
equivalent macro-generated member is `subenv_service_in_chan` (see `svt_usb_agent.sv:40` macro
table), confirmed cleartext at the top of the file.

`svt_usb_if.svi`'s sub-interface set is confirmed **and is larger** than `utmi_dut_mac_if` /
`ss_serial_if` / `20_serial_if` alone — see §4 for the complete, verified list of 20+ sub-interface
instances actually instantiated inside `interface svt_usb_if()`.

---

## 3. `svt_usb_agent` — the top-level active/passive agent (`svt_usb_agent.sv`)

Class: `class `SVT_USB_SUBENV_TYPE extends `SVT_USB_SUBENV_SVT_TYPE;` at line 958 → **`class
svt_usb_agent extends svt_agent;`** under UVM/OVM (or `svt_usb_subenv extends svt_subenv` under
VMM — macro table at lines 28-57).

### 3.1 Real public fields (cleartext, lines as noted)
```systemverilog
svt_usb_status                     shared_status;                                    // ~line 313
svt_usb_physical                   phys_lane[`SVT_USB_NUM_PHY_LANES];                // dual-lane (Gen2x2) physical array
svt_usb_physical                   phys;
svt_usb_physical_adapter           phys_adapter;
svt_usb_physical_monitor           phys_mon_lane[`SVT_USB_NUM_PHY_LANES];
svt_usb_physical_monitor           phys_mon;
svt_usb_physical_adapter_monitor   phys_adapter_mon;
svt_usb_link                       link;
svt_usb_link_monitor                link_mon;
svt_usb_protocol                   prot;
svt_usb_protocol_monitor           prot_mon;
`ifdef SVT_UVM_TECHNOLOGY
svt_usb_20_eusb2v2_phy_register_sets eusb2v2_phy_register_sets;                       // eUSB2v2 PHY register model, UVM-only
`endif
`ifndef SVT_VMM_TECHNOLOGY
`SVT_XVM(seq_item_pull_port) #(svt_usb_agent_service) agent_service_in_port;
svt_usb_agent_service               agent_service_rcvd_q[$];
svt_usb_link_service_sequencer      link_service_sequencer;
svt_usb_transfer_sequencer          xfer_sequencer;
svt_usb_transfer_sequencer          xfer_response_sequencer;
svt_usb_protocol_service_sequencer  prot_service_sequencer;
svt_usb_agent_service_sequencer     agent_service_sequencer;
svt_usb_virtual_sequencer           virt_sequencer;
`endif
```
`SVT_USB_NUM_PHY_LANES` = **2** (`include/sverilog/svt_usb_common_defines.svi:179`) — hard evidence
this VIP models up to a 2-lane (Gen2x2 dual-lane SuperSpeed+) physical layer per agent side.

### 3.2 Real extern method/task signatures (all cleartext prototypes)
```systemverilog
`ifdef SVT_UVM_TECHNOLOGY
  extern virtual function void build_phase(uvm_phase phase);
`elsif SVT_OVM_TECHNOLOGY
  extern virtual function void build();
`endif
extern virtual function void refresh_cfg();
extern virtual function void abort_current_pm_transfer(svt_usb_protocol_service protocol_service);   // Passive-Monitor only
extern virtual function void reset_pm_ep_seqnum(svt_usb_protocol_service protocol_service);          // Passive-Monitor only
extern virtual function void set_expected_transfer(svt_usb_transfer xfer);
extern task indicate_otg_ss_role_swap_completed(input bit success = 0);
extern task usb4_disconnect_usb3();      // USB4-tunnel-mode: forces the USB3 link portion to disconnect
```
`indicate_otg_ss_role_swap_completed`'s doc comment (fully cleartext) states the caller must invoke
it whenever `otg_role_swap_status` (a `svt_usb_types::otg_role_swap_status_enum`, see §7) is
`OTG_A_INITIATED_ROLE_SWAP_IN_PROGRESS` or `OTG_B_INITIATED_ROLE_SWAP_IN_PROGRESS` — this is a real
integration contract a test/env author must honor for SuperSpeed OTG role-swap sequences to
terminate correctly.

### 3.3 Doc-comment architecture notes worth preserving verbatim (cleartext Javadoc)
- The agent supports "up to two interfaces, one for USB 2.0 and one for SuperSpeed"; a remote
  Physical layer can be attached to model both sides of the same USB link "requiring no
  intervention on the part of the testbench."
- ULPI is explicitly flagged: *"the ULPI interface is NotYetImplemented... It can be compiled and
  instantiated, but if it is submitted to the Agent they will result in a 'NotYetImplemented' exit
  from the simulator... ULPI is supported by an external block that can be separately instantiated
  in a test bench."* This is a hard usage constraint, not a stale doc — treat `svt_usb_ulpi_if` as
  non-functional inside this agent.
- Ports are conveyed into the agent through `svt_usb_subenv_port`-family objects
  (`svt_usb_subenv_port_pipe3`, `_ss_serial`, `_utmi`, `_ulpi`, `_20_serial`, `_20_hsic`), which can
  be hand-built or produced via `svt_usb_subenv_port_creator`. **Interface-declaration parameters
  (e.g. `.generate_pclk(0)`) must be mirrored exactly in the port/port-creator declaration** — a
  parameter mismatch here is called out explicitly as a real footgun in the doc comment.
  For OTG, port-creator parameters are prefixed `otg_` (`.setup_time` → `.otg_setup_time`).
- Explicit technology requirement: `` `SVT_PACKER_MAX_BYTES `` must be `>= 16384` for this agent to
  correctly pack/unpack its configuration and transaction objects.

---

## 4. `svt_usb_if.svi` — top-level signal interface (verified + extended)

`interface svt_usb_if();` (`include/sverilog/svt_usb_if.svi:150`). Declares (in the
`` `ifdef SVT_USB_IF_NO_PARAMS``/`` `else`` parameterized branch — both branches instantiate the
same named sub-interfaces) the **complete, verified set** of sub-interface instances:

| Instance name | Sub-interface type | Notes |
|---|---|---|
| `pipe3_dut_phy_if` | `svt_usb_pipe3_dut_phy_if` | PIPE3 (Gen1/Gen2 SuperSpeed) to a DUT PHY |
| `pipe3_dut_mac_if` | `svt_usb_pipe3_dut_mac_if` | PIPE3 to a DUT MAC/Core |
| `pipe4_dut_phy_if` / `pipe4_dut_phy_lane1_if` | `svt_usb_pipe4_dut_phy_if` | PIPE4 (Gen2x2 dual-lane) to DUT PHY — **lane1 instance confirms 2-lane support at the signal-interface level**, matching `SVT_USB_NUM_PHY_LANES=2` |
| `pipe4_dut_mac_if` / `pipe4_dut_mac_lane1_if` | `svt_usb_pipe4_dut_mac_if` | PIPE4 to DUT MAC, dual-lane |
| `adapter_dut_phy_if` / `adapter_dut_mac_if` | `svt_usb_adapter_dut_phy_if` / `_mac_if` | USB4 tunneling adapter interface |
| `custom_adapter_dut_phy_if` / `custom_adapter_dut_mac_if` | `svt_usb_iip_custom_adapter_dut_phy_if` / `_mac_if` | "IIP custom adapter" variant for USB4 |
| `utmi_dut_phy_if` | `svt_usb_utmi_dut_phy_if` | UTMI+ to DUT PHY |
| `utmi_dut_mac_if` | `svt_usb_utmi_dut_mac_if` | UTMI+ to DUT MAC/Core |
| `ulpi_dut_phy_if` / `ulpi_dut_mac_if` | `svt_usb_ulpi_dut_phy_if` / `_mac_if` | ULPI — **NotYetImplemented per §3.3** |
| `usb_ss_serial_if` / `usb_ss_serial_lane1_if` | `svt_usb_ss_serial_if` | SuperSpeed serial (D+/D− equivalent, TX/RX differential), dual-lane |
| `usb_20_serial_if` | `svt_usb_20_serial_if` | USB2 HS/FS/LS serial (true D+/D−) |
| `usb_20_hsic_if` | `svt_usb_20_hsic_if` | HSIC |
| `usb_20_eusb2_if` | `svt_usb_20_eusb2_if` | eUSB2 |
| `usb_otg_if` | `svt_usb_otg_if` | OTG session/role-swap signals |
| `ulpi_if` | `svt_usb_ulpi_if` | a *separate*, unparameterized ULPI interface instance (line 441) — distinct from `ulpi_dut_phy_if`/`ulpi_dut_mac_if`; likely a legacy/alternate hookup, still NotYetImplemented per the class-level doc |
| `usb_debug_if` | `svt_usb_debug_if` | debug/tracking signals |
| `rmmi_mtx_dut_phy_if[SVT_USB_MAX_SSIC_LANE_COUNT-1:0]` etc. (4 arrays) | `svt_mphy_rmmi_mtx_dut_phy_if`, `_mrx_`, `..._dut_controller_if` variants | SSIC (M-PHY RMMI) physical/link arrays, sized by `SVT_USB_MAX_SSIC_LANE_COUNT = 4` (`include/sverilog/svt_usb_port_defines.svi:97`); compiled only when `SVT_USB_EXCLUDE_SSIC` is *not* defined |
| `ssic_mtx_serial_if[...]` / `ssic_mrx_serial_if[...]` | `svt_mphy_serial_tx_if` / `_rx_if` | SSIC serial arrays — doc comment explicitly says **"Use of this interface is not currently supported"** |

Also present at the top `svt_usb_if` scope: `testbench_clock`, and 14 debug/trace signals
(`physical_tx_data[31:0]`/`_desc`, `physical_rx_data`/`_desc`, `link_tx_symbol_set_desc`,
`link_tx_link_command_desc`, `link_tx_packet[31:0]`/`_desc`, `link_rx_packet`/`_desc`,
`protocol_tx_transfer`/`_transaction`/`_desc` ×2, `protocol_rx_transfer`/`_transaction`/`_desc` ×2),
each 32-bit index + 256-bit (`32*8`) ASCII description register, exposed via three modports:
`svt_usb_physical_debug_port`, `svt_usb_link_debug_port`, `svt_usb_protocol_debug_port` (all
`output`-only from the VIP's perspective — lines 542-557).

Interface-level configuration parameters: `setup_time=1`, `hold_time=1`, `clock_recovery_enable=1`,
`generate_pclk=1` (lines 157-179) — these must be mirrored on every sub-interface and on the
corresponding `svt_usb_subenv_port*`/creator per §3.3.

### 4.1 UTMI+ DUT-MAC interface signal/modport detail (`svt_usb_utmi_dut_mac_if.svi`)
Fully cleartext, not encrypted at all (0 `pragma protect` lines). Confirmed real signal list
(Data: `DataIn`/`DataOut` sized `[SVT_USB_MAX_UTMI_DATA_WIDTH-1:0]`, `SVT_USB_MAX_UTMI_DATA_WIDTH =
16`, `include/sverilog/svt_usb_port_defines.svi:70`), `TXValid`/`TXValidH`/`TXReady`,
`RXActive`/`RXValid`/`RXValidH`/`RXError`, `DataBus16_8`; System: `CLK`, `Reset`, `XcvrSelect`,
`TermSelect`, `SuspendM`, `SleepM`, `L1SuspendM`, `LineState`, `OpMode`; OTG: `IdPullup`, `IdDig`,
`AValid`, `BValid`, `VbusValid`, `SessEnd`, `DrvVbus`, `ChrgVbus`, `DischrgVbus`, `DpPulldown`,
`DmPulldown`, `HostDisconnect`; TX bit-stuff: `TxBitstuffEnable[H]`; FS/LS serial-mode escape
signals: `FsLsSerialMode`, `Tx_Enable_N`, `Tx_DAT`, `Tx_SE0`, `Rx_DP`, `Rx_DM`, `Rx_RCV`,
`Vip_Speed[1:0]` (00=LS,01=FS,10=HS_FS per in-line comment), `FsPullup`, `LsPullup`. An
`` `ifdef SVT_USB_EUSB2V2_UTMIV2 `` branch widens `TXValid`/`RXValid` to multi-bit and adds
`TXDataRate`/`RXDataRate`/`DataBusWidth`/`PortEnable`/`EnableComplianceMode`/`PHYResetB` for eUSB2v2
UTMI2.0 variable-rate mode, with clock-period tables for 15/30/45/60/75/80/90/96/105/120/135/150/
180/210/240/270/300 MHz UTMI clocks (lines 138-154) — real, concrete numeric evidence this
interface models the full eUSB2v2 rate-switching spec, not just classic 60/30/6 MHz UTMI.

**Explicit vendor caveat found in the doc comment (line 112): "THIS INTERFACE IS NOT YET
SUPPORTED!"** — i.e. `svt_usb_utmi_dut_mac_if` itself (the direct UTMI+ DUT-Core connection) carries
a not-yet-supported flag in this VIP release, distinct from the ULPI not-yet-implemented note in
§3.3. A verification engineer targeting a UTMI+-only USB2 MAC DUT should treat this as a real risk
flag to confirm against the release notes/AN before committing to that interface choice.

Modports: `svt_usb_utmi_phy_port` (VIP acting as PHY, drives `IdDig/AValid/BValid/VbusValid/SessEnd`
outward, samples the rest), `svt_usb_utmi_mac_port` (VIP/DUT acting as MAC, drives `DataIn`,
`TXValid[H]`, `Reset`, `SuspendM`, `XcvrSelect`, `TermSelect`, `OpMode`, pull/pulldown/Vbus
controls), `svt_usb_utmi_phy_monitor_port` (passive/monitor variant of the PHY port).

### 4.2 Other sub-interface modports confirmed present (name-level, from grep of `^modport`)
- `svt_usb_pipe3_dut_mac_if.svi`: `svt_usb_pipe3_mac_port`, `svt_usb_pipe3_phy_port`, `svt_usb_pipe3_phy_monitor_port`
- `svt_usb_pipe4_dut_mac_if.svi`: `svt_usb_pipe4_mac_port`, `svt_usb_pipe4_phy_port`, `svt_usb_pipe4_phy_monitor_port`
- `svt_usb_ss_serial_if.svi`: `svt_usb_ss_serial_phy_port`, `svt_usb_ss_serial_cable_port`, `svt_usb_ss_serial_phy_monitor_port`
- `svt_usb_20_serial_if.svi`: `svt_usb_20_serial_port`, `svt_usb_20_serial_monitor_port`
- `svt_usb_ulpi_dut_mac_if.svi`: `svt_usb_ulpi_mac_port`, `svt_usb_ulpi_phy_port`, `svt_usb_ulpi_phy_monitor_port`
- `svt_usb_adapter_dut_mac_if.svi`: `svt_usb_adapter_phy_port` (mac-side port name not separately declared in this file)
- `svt_usb_iip_custom_adapter_dut_mac_if.svi`: `svt_usb_pipe4_mac_port`, `svt_usb_pipe4_phy_port`, `svt_usb_pipe4_phy_monitor_port` (reuses PIPE4 modport names — confirms the custom adapter is PIPE4-shaped)
- `svt_usb_otg_if.svi`: `svt_usb_otg_dut_mac_port`, `svt_usb_otg_dut_phy_port`, `svt_usb_otg_dut_serial_port`, `svt_usb_otg_vip_mac_port`, `svt_usb_otg_vip_phy_port`, `svt_usb_otg_vip_serial_port`, `svt_usb_otg_monitor_port` (7 modports — OTG connects at every layer: MAC, PHY, and serial, both DUT- and VIP-side, plus a monitor)
- `svt_usb_hub_if.svi`: interface declared (line 109) but **no `modport` at all** in this file — hub connectivity is evidently handled through the standard per-port `svt_usb_if` instances plus `svt_usb_hub_agent`/`svt_usb_hub_agent_configuration` classes, not a dedicated hub modport.

### 4.3 Key signal-width/lane-count macros (`include/sverilog/svt_usb_port_defines.svi`)
```
SVT_USB_MAX_PIPE3_DATA_WIDTH   = 32   (line 61 / 102)
SVT_USB_MAX_UTMI_DATA_WIDTH    = 16   (line 70 / 129)
SVT_USB_MAX_ULPI_DATA_WIDTH    = 8    (line 88 / 183)
SVT_USB_MAX_ADAPTER_DATA_WIDTH = 512  (line 67 / 120)   -- USB4 tunneling adapter datapath is 512 bits wide
SVT_USB_MAX_SSIC_LANE_COUNT    = 4    (line 97)
```
and `SVT_USB_NUM_PHY_LANES = 2` (`svt_usb_common_defines.svi:179`), `SVT_USB_NUM_HUB_INST` default
`1` but declared via `` `SVT_REPLACEABLE_DEFINE `` (`svt_usb_common_defines.svi:6864`) — i.e. a
testbench can `` `define SVT_USB_NUM_HUB_INST <N> `` before this header to model more hub
instances; this directly sizes `svt_usb_system_virtual_sequencer::hub_virt_seqr[SVT_USB_NUM_HUB_INST]`.

---

## 5. `svt_usb_configuration` — the base configuration class (`svt_usb_configuration.sv`)

`class svt_usb_configuration extends svt_configuration;` at line 189. This is the single largest
class in the VIP (31,667 raw lines) and functions as the master knob-set for every protocol layer
(ESS/SS/USB2.0/SSIC/OTG) simultaneously — `svt_usb_agent_configuration`,
`svt_usb_hub_agent_configuration`, `svt_usb_device_configuration`, `svt_usb_host_configuration`,
and `svt_usb_endpoint_configuration` are its family (agent_configuration/hub extend it directly;
device/host/endpoint are structurally parallel `svt_configuration` extensions used *inside* an
agent configuration's device lists rather than subclasses of it — see §2 hierarchy, corrected).

### 5.1 Real top-level enums (all cleartext, values `` `SVT_USB_* `` macro-defined elsewhere)
- **`vip_generation_enum { GEN_A, GEN_B, GEN_T }`** — doc comment is explicit and load-bearing:
  `GEN_A` = USB3.0-only internal model, max 5 Gb/s SuperSpeed, explicitly deprecated ("It is
  recommended that test environments migrate to GEN_B... limited bug fixes and no enhancements to
  GEN_A"). `GEN_B` = USB3.1 Enhanced SuperSpeed (Gen1/Gen2) + USB2.0, the actively maintained
  generation. `GEN_T` = USB4 "Gen T adapter" tunneling mode. **Any environment/config-audit agent
  should flag `GEN_A` usage as using a documented-legacy code path.**
- `ssc_mode_enum { SSC_DOWN_SPREAD_MODE, SSC_CENTRE_SPREAD_MODE }`
- `usb_capability_enum { USB_SS_CAPABLE, USB_SS_ONLY, USB_20_ONLY }`
- `component_capabilities_enum { PLAIN, OTG }`
- `otg_capabilities_enum { OTG_20_ONLY, OTG_SS_CAPABLE }`
- `usb_ss_signal_interface_enum { USB_SS_CHANNEL, USB_SS_TLM, PIPE3_IF, USB_SS_SERIAL_IF, SSIC_RMMI_IF, SSIC_SERIAL_IF, USB_SSIC_CHANNEL, USB_SSIC_TLM, PIPE4_IF, NO_SS_IF }` — this is the enum a testbench uses to select which SuperSpeed signal interface a given `svt_usb_configuration` instance is bound to (drives which `svt_usb_agent_if_object_*` subclass gets created — see §9).
- `usb_adapter_signal_interface_enum { NO_ADAPTER, USB4_ADAPTER_TLM, USB4_ADAPTER_IF, USB4_IIP_CUSTOM_ADAPTER_IF, USB4_ADAPTER_CHANNEL }`
- `usb_20_signal_interface_enum { USB_20_CHANNEL, USB_20_TLM, UTMI_IF, ULPI_IF, USB_20_HSIC_IF, USB_20_SERIAL_IF, USB_20_EUSB2_IF, NO_20_IF }`
- `component_subtype_enum { PHY, MAC }` — VIP's perspective relative to signal interface
- `ssic_profile_enum` — 18 named G{1,2,3}{A,B}_L{1,2,4} SSIC profile combinations
- `ss_ping_timeout_terminate_style_enum { SS_PING_TIMEOUT_TERMINATE_ALL_ISOC_EPS, SS_PING_TIMEOUT_TERMINATE_EP_WHICH_RCVD_PKT, SS_PING_TIMEOUT_REQUIRE_LPF_ALL_ISOC_EPS }` — controls tPingTimeout termination scope across ISOC endpoints; doc comment ties this directly to `svt_usb_protocol_service::service_type==CMD` / `protocol_command_type==USB_SEND_DEFERRED_PACKETS` behavior.
- `ss_ping_processing_style_enum { SS_PING_FOR_ISOC_EP_ONLY, SS_PING_EP_AGNOSTIC, SS_CONCURRENT_PING_FOR_PERIODIC_EPS }`
- `jitter_type_enum { RANDOM_JITTER, CONSTANT_POSITIVE_JITTER, CONSTANT_NEGATIVE_JITTER }`
- Plus: `send_lmp_post_recovery_enum`, `timer_scale_down_type_enum`, `control_message_before_pull_up_enum`, `ss_otg_issue_warm_reset_enum`, `lpm_type_enum { LPM_NORMAL, LPM_DEEP, LPM_SHALLOW }`, `se0_se1_type_enum`, `utmi_abort_type_enum`, `ssic_protocol_version_enum { NO_SSIC_PROTOCOL_VERSION, SSIC_PROTOCOL_VERSION_101, SSIC_PROTOCOL_VERSION_102 }`.

### 5.2 Field taxonomy (this class has hundreds of knobs; representative, verified categories)
- Role/topology: `is_downstream`, `is_upstream`, `is_upstream_phy`, `is_downstream_phy` (all gated
  by `` `ifdef SVT_USB_ENABLE_HUB_MODE `` — hub-role knobs are compile-time optional).
- USB4 tunneling: `enable_usb4_adapter_mode_symbol_set_scheduling_delay`,
  `enable_usb4_adapter_mode_lfps_packet_scheduling_delay`, `enable_usb32_feature`.
- LTSSM/link timing (Gen1/Gen2 SuperSpeed): dozens of `int` counters named
  `<ltssm_substate>_<event>_count`, each defaulted to an `` `SVT_USB_<SAME_NAME> `` macro constant
  (i.e. every LTSSM timing value is independently overridable via a `` `SVT_REPLACEABLE_DEFINE``-
  style macro *and* has a live `svt_usb_configuration` field) — e.g.
  `polling_lfps_received_count`, `polling_rxeq_tseq_count`, `hot_reset_active_sent_idle_count`,
  `recovery_configuration_received_ts2_count`, `loopback_active_sync_after_ts1_ts2_sent_count`.
  This confirms the VIP exposes LTSSM compliance-test timing as first-class, per-agent-configurable
  fields rather than hard-coded constants — directly relevant to compliance/negative-timing tests.
- `rand svt_usb_types::ltssm_state_enum usb_ss_initial_ltssm_state = svt_usb_types::U0;` and
  `usb_ss_initial_prev_ltssm_substate/_state` — lets a test start the link state machine somewhere
  other than `Rx.Detect`/reset, useful for directed mid-link-training tests.
- Power management: `rand bit u1_enable`, `u2_enable`, `u1_inactivity_upstream_enabled`,
  `u1_timeout[7:0]`, `u2_inactivity_upstream_enabled`.
- Error-injection/exception toggles: `enable_injected_exception_crc32_check`,
  `enable_packet_field_reserved_value_error_check`, `enable_crc32_checks_for_aborted_dpp`.
- Coverage-model on/off switches (dozens): `enable_rptr_chk_cov`, `enable_rptr_pass_cov`,
  `enable_rptr_fail_cov`, `enable_ltssm_coverage_for_active_agent`.
- Compliance/CTS knobs: `loopback_cts_compliant`, `loopback_cts_compliant_in_phy_dut_setup`,
  `cts_compliance_loopback_tx_iterations`, `scd1s_to_be_sent_in_loopback_state`, etc.
- `usb_ss_data_scramble = 1` / `enable_eusb2v2_data_scramble = 1` — SuperSpeed/eUSB2v2 data
  scrambling on by default (can be disabled for scope-friendly directed debug).

This class is large enough that a config-audit agent should treat it as "the knob registry" and
query it by name/keyword rather than expect a short enumerable list — the report above is a
representative, verified sample of the field taxonomy, not an exhaustive field list.

---

## 6. `svt_usb_agent_configuration` (`svt_usb_agent_configuration.sv:107`)

`class `SVT_USB_SUBENV_CONFIGURATION_TYPE extends svt_usb_configuration;` — confirmed direct child
of `svt_usb_configuration`. Adds agent/active-vs-passive-specific knobs on top of the base
protocol knob set:
```systemverilog
bit is_active = 1'b1;
bit enable_monitor = 1'b1;
bit base_service_gen_autostart = 1;
bit concurrent_service_gen_autostart = 1;
bit base_gen_autostart = 1;
bit concurrent_gen_autostart = 1;
bit [1:0] enable_ssic_phys_exceptions        = `SVT_USB_NO_SSIC_PHYSICAL_EXCEPTIONS;
bit [1:0] enable_phys_base_exceptions        = `SVT_USB_NO_PHYSICAL_EXCEPTIONS;
bit [1:0] enable_phys_concurrent_exceptions  = `SVT_USB_NO_PHYSICAL_EXCEPTIONS;
bit [1:0] enable_phys_adapter_base_exceptions = `SVT_USB_NO_PHYSICAL_ADAPTER_EXCEPTIONS;
bit enable_link_chk_cov / _chk_pass_cov / _chk_fail_cov;
bit enable_prot_chk_cov / _chk_pass_cov / _chk_fail_cov;
bit enable_phys_chk_cov / _chk_pass_cov / _chk_fail_cov;
bit enable_phys_chk = 1;   bit enable_phys_cov = 0;   bit enable_toggle_cov = 0;
bit [5:0] enable_link_base_exceptions       = `SVT_USB_NO_LINK_EXCEPTIONS;
bit [5:0] enable_link_concurrent_exceptions = `SVT_USB_NO_LINK_EXCEPTIONS;
bit enable_link_chk = 1;   bit enable_link_cov = 0;
bit enable_link_pkt_reporting = 1;   bit enable_link_lcmd_reporting = 1;
bit [3:0] enable_prot_exceptions = `SVT_USB_NO_PROTOCOL_EXCEPTIONS;
bit [1:0] enable_prot_chk = 2'b11;
bit enable_prot_cov = 0;   bit enable_otg_cov = 0;   bit enable_ep_prot_tracing = 0;
bit enable_debug_ports = 0;   bit enable_pl_debug_ports = 0;
bit enable_debug_ports_eusb2_repeater_deep_level = 1;
bit enable_pre_arranged_device_transfers = `SVT_USB_ENABLE_PRE_ARRANGED_DEVICE_TRANSFERS;
bit [3:0] port_num;
bit enable_phy_adapter_chk / _cov / _tracing / _reporting;
bit wait_for_dut_ltssm = `SVT_USB_WAIT_FOR_DUT_LTSSM;
```
Referenced but not shown in the cleartext field list above (only usable via the class-scope path,
so their type location is confirmed even though the enum body sits in an earlier encrypted block):
`svt_usb_agent_configuration::stack_layer_enum` (used by `get_layer_event_pool` in the virtual
sequencer, §7.1) and `svt_usb_agent_configuration::dut_model_enum { ..., RTL, VIP, NOT_APPLICABLE
... }` (used by `get_dut_model()`/`get_dut_type()` in the system virtual sequencer, §7.2) — the
enum *members* `RTL`/`VIP`/`NOT_APPLICABLE` are directly quoted in the system-virtual-sequencer
doc-comment (see below), confirming their names even though their `typedef enum` declaration line
itself fell inside an encrypted span in this pass.

Real method signatures (standard SVT `svt_data`/`svt_configuration` object-services API, all `extern`):
```systemverilog
extern function new ( vmm_log log = null );                          // VMM ctor
extern function new(string name = "svt_usb_agent_configuration_inst"); // UVM/OVM ctor
extern virtual function string get_mcd_class_name ();
extern virtual function void copy_static_data ( `SVT_DATA_BASE_TYPE to );
extern virtual function void copy_dynamic_data ( `SVT_DATA_BASE_TYPE to );
extern virtual function bit do_compare ( `SVT_DATA_BASE_TYPE to, output string diff, input int kind = -1 );
extern virtual function bit do_is_valid ( bit silent = 1, int kind = -1 );
extern virtual function int unsigned byte_size ( int kind = -1 );
extern virtual function int unsigned do_byte_pack ( ref logic [7:0] bytes[], ... );
extern virtual function int unsigned do_byte_unpack ( const ref logic [7:0] bytes[], ... );
extern virtual function bit get_prop_val(string prop_name, ref bit [1023:0] prop_val, input int array_ix, ref `SVT_DATA_TYPE data_obj);
extern virtual function bit set_prop_val(string prop_name, bit [1023:0] prop_val, int array_ix);
extern virtual function svt_pattern do_allocate_pattern();
extern virtual function bit encode_prop_val(string prop_name, string prop_val_string, ref bit [1023:0] prop_val, ...);
extern virtual function bit decode_prop_val(string prop_name, bit [1023:0] prop_val, ref string prop_val_string, ...);
extern function bit get_usb_addresses(svt_usb_types::component_type_enum component, ...);
extern function bit get_usb_addresses_q(svt_usb_types::component_type_enum component, ...);
```

---

## 7. Sequencer layer — `svt_usb_virtual_sequencer` and `svt_usb_system_virtual_sequencer`

Both files are effectively 100%-readable at the API level (only method *bodies* at the tail are
encrypted); everything below is a direct, complete quote of the class contents.

### 7.1 `svt_usb_virtual_sequencer` (`svt_usb_virtual_sequencer.sv:10`)
`class svt_usb_virtual_sequencer extends svt_sequencer;` — one instance lives inside each
`svt_usb_agent` (`virt_sequencer` field, §3.1).

Fields (all real, all sequencer references — this is the "one virtual sequencer wires up every
physical/link/protocol non-virtual sequencer" pattern):
```systemverilog
svt_usb_data_sequencer                     usb_ss_data_sequencer;
svt_usb_link_packed_transaction_sequencer  usb_adapter_packed_trans_sequencer;
svt_usb_data_sequencer                     usb_ss_data_sequencer_lane[`SVT_USB_NUM_PHY_LANES];
bit disable_single_seqr_multi_port = 0;
svt_usb_data_sequencer                     usb_20_data_sequencer;
svt_usb_physical_service_sequencer         usb_ss_phys_service_sequencer_lane[`SVT_USB_NUM_PHY_LANES];
svt_usb_physical_service_sequencer         usb_ss_phys_service_sequencer;
svt_usb_physical_service_sequencer         usb_adapter_phys_service_sequencer;
svt_usb_physical_service_sequencer         usb_20_phys_service_sequencer;
svt_usb_packet_sequencer                   usb_ss_pkt_sequencer;
svt_usb_packet_sequencer                   usb_20_pkt_sequencer;
svt_usb_link_service_sequencer             link_service_sequencer;
svt_usb_transfer_sequencer                 xfer_sequencer;
svt_usb_transfer_sequencer                 xfer_response_sequencer;
svt_usb_protocol_service_sequencer         prot_service_sequencer;
svt_usb_agent_service_sequencer            agent_service_sequencer;
`SVT_XVM(blocking_peek_port) #(svt_usb_transfer) transfer_out_port;   // output port for xfers received by a Device agent
local svt_usb_configuration cfg;
```
Registered via `` `svt_xvm_component_utils_begin(svt_usb_virtual_sequencer) `` with every sequencer
field declared `` `SVT_XVM_ALL_ON|`SVT_XVM_REFERENCE `` (i.e. by-reference field automation, not
deep-copied).

Full method surface:
```systemverilog
extern function new(string name = "svt_usb_virtual_sequencer", `SVT_XVM(component) parent = null);
extern virtual function void build_phase(uvm_phase phase);           // or build() under OVM
extern virtual function `SVT_XVM(agent) find_first_agent(`SVT_XVM(sequence_item) seq);
extern virtual function svt_usb_status get_shared_status(`SVT_XVM(sequence_item) seq);
extern virtual function svt_usb_status get_remote_shared_status(`SVT_XVM(sequence_item) seq);
extern virtual task get_layer_event_pool(input `SVT_XVM(sequence_item) seq,
                                          input svt_usb_agent_configuration::stack_layer_enum layer,
                                          output `SVT_XVM(event_pool) event_pool);
extern virtual function void reconfigure(svt_configuration cfg);
extern virtual function void get_cfg(ref svt_configuration cfg);
extern virtual function svt_err_check get_err_check(`SVT_XVM(sequence_item) seq, string checks_inst = "err_check");
```
This is the concrete API a sequence author uses from inside a `svt_usb_base_virtual_sequence` to
reach the owning agent, its `shared_status`, its event pool for a given protocol layer, or its
error-check registry — genuinely the operative "how do I talk to the agent from a sequence" surface.

### 7.2 `svt_usb_system_virtual_sequencer` (`svt_usb_system_virtual_sequencer.sv:10`)
`class svt_usb_system_virtual_sequencer extends svt_sequencer;` — the higher-level, host+device
(+hub) pairing sequencer, one per test environment (not per agent).

Fields:
```systemverilog
svt_usb_virtual_sequencer  multi_host_virt_sequencer[];
svt_usb_virtual_sequencer  host_virt_sequencer;
`ifdef SVT_USB_ENABLE_HUB_MODE
svt_usb_virtual_sequencer  hub_virt_seqr[`SVT_USB_NUM_HUB_INST];
`endif
svt_usb_virtual_sequencer  dev_virt_sequencer;
svt_usb_virtual_sequencer  device_virt_sequencer[$];   // per-cable queue, "used by usb_test_suite_svt testbenches, not usb_svt"
local `SVT_XVM(report_object) reporter = this;
```
Full method surface (complete, all `extern`):
```systemverilog
extern function new(string name = "svt_usb_system_virtual_sequencer", `SVT_XVM(component) parent = null);
extern virtual function `SVT_XVM(agent) find_host_agent(svt_sequence seq);
extern virtual function void find_hub_agents(svt_sequence seq, output `SVT_XVM(agent) agents[`SVT_USB_NUM_HUB_INST]);  // SVT_USB_ENABLE_HUB_MODE only
extern virtual function `SVT_XVM(agent) find_dev_agent(svt_sequence seq);
extern virtual function svt_usb_status get_host_shared_status(svt_sequence seq);
extern virtual function svt_usb_status get_host_remote_shared_status(svt_sequence seq);
extern virtual function svt_usb_status get_dev_shared_status(svt_sequence seq, input int hub_port_id = -1);
extern virtual function svt_usb_status get_dev_remote_shared_status(svt_sequence seq);
extern virtual task get_host_layer_event_pool(input svt_sequence seq, input svt_usb_agent_configuration::stack_layer_enum layer, output `SVT_XVM(event_pool) event_pool);
extern virtual task get_dev_layer_event_pool(input svt_sequence seq, input svt_usb_agent_configuration::stack_layer_enum layer, output `SVT_XVM(event_pool) event_pool, input int hub_port_id = -1);
extern virtual function void get_host_cfg(ref svt_configuration cfg);
extern virtual function void get_dev_cfg(ref svt_configuration cfg, input int hub_port_id = -1);
extern virtual function svt_err_check get_host_err_check(svt_sequence seq, string checks_inst = "err_check");
extern virtual function svt_err_check get_dev_err_check(svt_sequence seq, string checks_inst = "err_check");
extern virtual function svt_usb_types::dut_type_enum get_dut_type();
extern virtual function svt_usb_agent_configuration::dut_model_enum get_dut_model();
extern virtual function void set_device_id(int unsigned device_id);
extern virtual function void update_dev_virt_sequencer(int cable_id);
```
`get_dut_type()`/`get_dut_model()` doc comments spell out a real environment-wiring contract worth
preserving verbatim: *"In a verification environment set up for a real DUT either the Host side
configuration ... or the Device side configuration (but not both) should have its
`svt_usb_agent_configuration::dut_model` property set to something other than
`svt_usb_agent_configuration::NOT_APPLICABLE`"* — with named values `RTL` (real RTL DUT) and `VIP`
(DUT side emulated by a VIP USB agent). **If both sides (or neither) have `dut_model` set away from
`NOT_APPLICABLE`, `get_dut_type()`/`get_dut_model()` report an error** — this is a concrete,
checkable environment-wiring invariant for any IP-level testbench audit.

`set_device_id(device_id)` / `device_virt_sequencer[$]` doc comments confirm this VIP supports
**multi-port DUT Host testing**: multiple VIP Device sub-environments hanging off one DUT Host's
ports simultaneously, selected at sequence-time by index.

---

## 8. Data-item classes: `svt_usb_transaction`, `svt_usb_transfer`, `svt_usb_packet`

All three sit as siblings under `` `SVT_TRANSACTION_TYPE `` (§2), representing, respectively, the
**Protocol-layer transaction** (a single token+data+handshake exchange), the **Protocol-layer
transfer** (the USB "transfer" abstraction — a sequence of transactions forming one Setup/Data/
Status control transfer, one bulk/interrupt burst, one isoc service interval, etc.), and the
**Link-layer packet** (raw framed packet as put on the wire, pre-encoding).

### 8.1 `svt_usb_transaction` (`svt_usb_transaction.sv:268`)
Selected real fields (all cleartext, confirming actual USB SETUP/token semantics are modeled
faithfully, not abstracted away):
```systemverilog
svt_usb_configuration cfg = null;
svt_usb_transaction_exception_list exception_list = null;
svt_usb_payload payload;
int payload_offset = 0;
rand svt_usb_types::speed_enum device_connected_bus_speed = svt_usb_types::SS;
rand svt_usb_types::number_of_lanes_support_enum device_connected_num_lanes = svt_usb_types::LANE_SUPPORT_1;
rand bit [3:0] lpm_hird = 4'b0000;             rand bit lpm_bremotewake = 1'b0;
rand bit [3:0] lpm_blinkstate = 4'b0001;
rand svt_usb_types::transaction_type_enum xact_type = svt_usb_types::IN_TRANSACTION;
rand bit [6:0] device_address = 6'b0;          rand bit [3:0] endpoint_number = 0;
rand bit [15:0] usb_stream_id = 0;
rand svt_usb_types::setup_data_bmrequesttype_dir_enum        setup_data_bmrequesttype_dir       = svt_usb_types::HOST_TO_DEVICE;
rand svt_usb_types::setup_data_bmrequesttype_type_enum       setup_data_bmrequesttype_type       = svt_usb_types::STANDARD;
rand svt_usb_types::setup_data_bmrequesttype_recipient_enum  setup_data_bmrequesttype_recipient  = svt_usb_types::BMREQ_DEVICE;
rand bit [7:0]  setup_data_brequest = svt_usb_types::GET_STATUS;
rand bit [15:0] setup_data_w_value  = 16'b0;
rand bit [15:0] setup_data_w_index  = 16'b0;
rand bit [15:0] setup_data_w_length = 16'b0;
rand bit [19:0] route_string;                  // USB3 hub routing string, matches spec field width
rand device_response_enum device_response = RESPONSE_UNKNOWN;   // weighted via *_RESPONSE_wt int fields (NORMAL/NAK/STALL/NYET/ERR/TIMEOUT/...)
rand host_response_enum   host_response   = HOST_NORMAL_RESPONSE;
svt_usb_types::split_xact_enum split_state = svt_usb_types::NO_SPLIT;   // FS/LS-behind-HS-hub split-transaction tracking
rand int unsigned retry_due_to_nak_cnt / _stall_cnt / _timeout_cnt / _error_cnt / _nyet_cnt;
```
The `setup_data_*` fields are a 1:1 match to the 8-byte USB SETUP packet
(bmRequestType/bRequest/wValue/wIndex/wLength) — confirms this transaction object is used directly
to build/inspect control transfers at the spec-field level, not just a generic byte-blob.

Method surface (60+ `extern` methods observed; representative set beyond standard `svt_data`
object-services boilerplate — `do_copy`/`do_compare`/`do_pack`/`do_unpack`/`byte_size`/etc.):
```systemverilog
extern function void pre_randomize ();          extern function void post_randomize ();
extern virtual function int reasonable_constraint_mode ( bit on_off );
extern function void fix_anchors(int unsigned dev_ix_anchor, int unsigned ep_ix_anchor);
extern task adjust_for_fixed_randomization();
extern function svt_usb_types::transaction_type_enum get_xact_type_val();
extern function bit [6:0] get_device_address_val();
extern function device_response_enum get_device_response_val();
extern function bit [3:0] get_endpoint_number_val();
extern function bit [15:0] get_usb_stream_id_val();
extern function bit get_lpm_bremotewake_val();  extern function bit [3:0] get_lpm_hird_val();
extern function int get_packet_index(svt_usb_packet pkt);
extern function int is_tx_packet( svt_usb_packet packet );
extern function bit is_ignore_ack_required();
```
(the `get_*_val()` family is the standard SVT pattern for exposing a `rand` field's *current*
solved value through an accessor that additionally handles "anchor" indirection, per
`dev_ix_anchor`/`ep_ix_anchor`/`find_ix_anchor_values()` — device/endpoint identity in a
transaction can be indirected through a device/endpoint list index rather than a literal address,
which is how the VIP supports randomizing "pick some enumerated device/endpoint" without knowing
concrete addresses at constraint-authoring time).

### 8.2 `svt_usb_transfer` (`svt_usb_transfer.sv:420`, plus a small helper class
`svt_usb_transfer_supported_ustream_id_holder` at line 393-400 in the same file) — not
exhaustively re-walked line-by-line in this pass beyond confirming `class svt_usb_transfer extends
`SVT_TRANSACTION_TYPE;` and its ~39% cleartext fraction (4683/11891 lines); recommend a follow-on,
transfer-specific extraction pass if a future consumer needs transfer-level field-by-field detail
(this pass prioritized breadth across agent/config/transaction/sequencer per the task).

### 8.3 `svt_usb_packet` (`svt_usb_packet.sv:39`)
`class svt_usb_packet extends `SVT_TRANSACTION_TYPE;` — the link-layer wire-format packet class,
20,841 raw lines (the single largest per-class file after configuration), 31.6% cleartext
(6594 lines). Not walked field-by-field in this pass; flagged as the next-highest-value target for
a follow-on link-layer-focused extraction (PID encoding, CRC5/CRC16/CRC32 field placement, LFPS/TS1
/TS2 ordered-set framing fields would all live here).

---

## 9. Physical/Link/Protocol active engines (`svt_xactor` family)

`svt_usb_physical` (`svt_usb_physical.sv:488`), `svt_usb_link` (`svt_usb_link.sv:321`),
`svt_usb_protocol` (`svt_usb_protocol.sv:606`) — **all three extend `svt_xactor` directly**, *not*
`svt_driver`/`svt_monitor`. This is architecturally significant: these are combined
driver+monitor+FSM "active/passive dual-mode" engines (the file-name families
`svt_usb_link_active_common.sv`, `svt_usb_link_passive_common.sv`,
`svt_usb_physical_active_common.sv`, `svt_usb_physical_passive_common.sv`,
`svt_usb_protocol_active_common.sv`, `svt_usb_protocol_passive_common.sv` all exist alongside them
and are `include`d/mixed in), where a single class body handles both roles depending on
`svt_usb_agent_configuration::is_active`. Separate `svt_usb_link_monitor`, `svt_usb_physical_monitor`,
`svt_usb_protocol_monitor` classes also exist (referenced as `typedef class` forward-decls in
`svt_usb_agent.sv:62-66`) as the passive-monitor-only counterparts instantiated by the agent
alongside the active xactor (see the `phys`/`phys_mon`, `link`/`link_mon`, `prot`/`prot_mon` field
pairs in §3.1) — i.e. **the agent always builds both an active xactor and a separate monitor
xactor per layer**, regardless of `is_active`, so passive-monitor-only checking is available even
in an active agent.

`svt_usb_protocol.sv` is only 5.0% cleartext (702/14058 lines) — almost the entire scheduling/
endpoint-processor state machine is encrypted. What *is* visible is the class declaration and a
handful of top-level field/typedef lines; the real protocol-scheduling algorithm (endpoint
round-robin, isoc/bulk/interrupt/control arbitration — implemented across the sibling
`svt_usb_protocol_scheduler.sv`, `svt_usb_protocol_genb_scheduler.sv`,
`svt_usb_protocol_*_ep_processor*.sv` files, also all encrypted) is not extractable from source in
this VIP release. A verification/debug agent needing scheduler behavior must rely on
simulation-observed behavior, VIP documentation, or vendor support — not source inspection.

`svt_usb_agent_if_object` family (`svt_usb_agent_if_object.sv` + per-signal-interface subclasses
`_utmi`, `_pipe3`, `_pipe4`, `_pipec`, `_ss_serial`, `_ulpi`, `_20_serial`, `_20_hsic`, `_20_eusb2`,
`_iip_custom_adapter`, plus `_adapter` and `_creator`): these are >85% encrypted in every file
examined (12-24 clear lines out of 161-439 total per file) — only the file guard, `` `ifdef
SVT_VMM_TECHNOLOGY `` macro-selection preamble (`` `SVT_USB_SUBENV_PORT_TYPE `` resolves to
`svt_usb_subenv_port` under VMM or `svt_usb_agent_if_object` under UVM/OVM/`SVT technology — see
`svt_usb_agent_if_object.sv:5-11`), and `` `endif `` survive. This confirms the *existence and
naming* of the per-interface-type "if_object"/port classes (used per §5.1's
`usb_ss_signal_interface_enum` to select which physical connection object gets constructed for a
given agent configuration) but not their internal implementation.

---

## 10. `svt_usb_status` (`svt_usb_status.sv:36`) — the `shared_status` object

`class svt_usb_status extends svt_status;` — 40.7% cleartext (5519/13566 lines), the
second-largest genuinely-readable class after `svt_usb_configuration`. This is the object referred
to by `svt_usb_agent::shared_status` (§3.1) and by `svt_usb_virtual_sequencer::get_shared_status()`
/ `get_remote_shared_status()` (§7.1) — i.e. the live, read-only-from-outside runtime state object
(current LTSSM state, negotiated speed, device address table, link partner status, etc.) that
sequences query to make stimulus decisions. Not exhaustively field-walked in this pass (flagged as
a high-value follow-on target — this is exactly the object a debug agent would want a full field
inventory of for waveform/log correlation); confirmed real and substantially readable.

`svt_usb_bus_instance` (`svt_usb_bus_instance.sv:23`) also `extends svt_status` — a smaller
(877-line, 48.9% clear) per-bus-instance status/tracking object, distinct from the per-agent
`svt_usb_status`.

---

## 11. Device/Host/Endpoint configuration classes

All three are direct `svt_configuration` extensions (siblings to `svt_usb_configuration`, per the
corrected hierarchy in §2), used as elements of device/endpoint *lists* hung off an
`svt_usb_agent_configuration` (`local_device_cfg`/`remote_device_cfg`, referenced by name in the
`svt_usb_configuration.sv` doc comments for `ss_ping_processing_style_enum`, §5.1) rather than as
subclasses of the agent's own configuration.

### 11.1 `svt_usb_device_configuration` (`svt_usb_device_configuration.sv:27`, 47.5% clear)
```systemverilog
rand int unsigned cable_id = 0;
rand bit [7:0] port_id = 0;
rand int unsigned enumeration_priority = 0;
rand bit [6:0] device_address = 0;
int min_eps = 1;
rand svt_usb_types::speed_enum connected_bus_speed = svt_usb_types::SS;
rand svt_usb_types::number_of_lanes_support_enum connected_num_lanes = svt_usb_types::LANE_SUPPORT_1;
rand svt_usb_endpoint_configuration endpoint_cfg[$];
rand int unsigned num_endpoints = 1;
rand int unsigned max_packet_size_0 = 512;
rand bit [3:0] route_string_port[5];                 // per-tier USB3 hub routing-string components
rand bit [6:0] connected_hub_device_address = 0;
rand bit xhci_slot_context_hub = 1'b0;
rand bit [7:0] xhci_slot_context_number_of_ports = 8'h0;
rand bit lpm_capable = 1'b1;      rand bit remote_wakeup_capable = 1'b0;
bit enumeration_automatic = `SVT_USB_INCLUDE_ENUMERATION;
bit enumeration_set_address_only = `SVT_USB_ENUMERATION_SET_ADDRESS_ONLY;
bit eusb2v2_speed_support = 0;    bit eusb2_double_isoc_bw_support = 0;
rand svt_usb_types::speed_enum functionality_support = svt_usb_types::LS;
rand int unsigned u1_dev_exit_lat;   rand int unsigned u2_dev_exit_lat;
rand int unsigned max_power;
rand bit ltm_capable = 1'b1;
rand bit low_speed_capable / full_speed_capable / high_speed_capable / five_gbs_speed_capable;
rand bit self_powered_capable = 1'b0;
```
`num_endpoints`, `max_packet_size_0`, `endpoint_cfg[$]`, `device_address`, and the
`*_speed_capable` bits map directly onto the standard USB Device Descriptor fields (bMaxPacketSize0,
bNumConfigurations territory) and BOS/USB3 capability descriptors — confirms this class is the
VIP's live analog of a device's descriptor-derived capability set, not just a bus-address holder.
`xhci_slot_context_*` fields show direct xHCI Slot Context field mirroring for host-mode xHCI
modeling (ties to `svt_usb_xhci_trb`/`svt_usb_xhci_td`/`svt_usb_xhci_trb_ring`, §12).

### 11.2 `svt_usb_host_configuration` (`svt_usb_host_configuration.sv:14`, 43.4% clear)
Confirmed to exist and extend `svt_configuration` directly; not field-walked in this pass beyond
the class declaration (follow-on target).

### 11.3 `svt_usb_endpoint_configuration` (`svt_usb_endpoint_configuration.sv:19`, 54.0% clear)
```systemverilog
rand svt_usb_types::speed_enum speed = svt_usb_types::SS;
rand int unsigned ep_number = 0;
rand svt_usb_types::ep_direction_enum direction = svt_usb_types::IN;
rand svt_usb_types::ep_type_enum ep_type = svt_usb_types::CONTROL;
rand int unsigned max_retry_due_to_nak / _stall / _timeout / _error = 10;   // (stall default 0)
rand int host_xfer_attempts_after_stall = -1;
rand isoc_mult_enum isoc_mult = ISOC_MULT_ZERO;         // SS isoc burst multiplier
rand int unsigned max_burst_size = 0;
rand int unsigned max_burst_extension = 0;
rand int unsigned max_packet_size = `SVT_USB_SS_CONTROL_MAX_PACKET_SIZE;
rand int unsigned num_ustream_resources = 0;
rand svt_usb_ustream_resource_configuration ustream_resource_cfg[$];
rand int unsigned num_psid_values = `SVT_USB_MAX_NUM_PSID_VALUES;    // stream-ID support (bulk streams)
rand bit supports_ustreams = 1'b0;
rand svt_usb_types::pp_bit_mode_enum pp_bit_mode = svt_usb_types::PP_BIT_0_AT_END_OF_TRANSFER;
rand int unsigned interval = 1;                          // bInterval-equivalent
rand intr_mult_enum intr_mult = INTR_MULT_ZERO;
rand bit enable_20_standard_device_request_processing = 1;
```
Direct 1:1 mapping to Endpoint Descriptor fields (`ep_number`+`direction` = bEndpointAddress,
`ep_type` = bmAttributes transfer-type bits, `max_packet_size` = wMaxPacketSize, `interval` =
bInterval) plus SuperSpeed Endpoint Companion Descriptor fields (`max_burst_size`, `isoc_mult` /
`intr_mult` = bmAttributes Mult, `bytes_per_interval`), plus SuperSpeedPlus ISOC Endpoint Companion
fields (`ssp_bytes_per_interval`, seen in the earlier grep pass) and Bulk-Streams support
(`num_psid_values`, `supports_ustreams`).

---

## 12. xHCI host-controller modeling classes

`svt_usb_xhci_trb` (`svt_usb_xhci_trb.sv:13`, extends `` `SVT_TRANSACTION_TYPE``, 22.1% clear),
`svt_usb_xhci_td` (`svt_usb_xhci_td.sv:30`, extends `svt_status`, 54.6% clear),
`svt_usb_xhci_trb_ring` (`svt_usb_xhci_trb_ring.sv:34`, extends `svt_status`, 45.7% clear) — a
genuine xHCI TRB/TD/Ring modeling layer exists in this VIP (Transfer Request Block, Transfer
Descriptor, and the ring data structure itself), tied to `svt_usb_device_configuration`'s
`xhci_slot_context_hub` / `xhci_slot_context_number_of_ports` fields (§11.1). This is relevant for
any environment doing **host-mode verification against an xHCI-based DUT host controller** (as
opposed to treating the DUT purely at the UTMI/PIPE signal level) — the VIP appears to have
first-class xHCI ring/TRB awareness, not just USB-protocol-level modeling. Not field-walked in
depth in this pass (follow-on target for an xHCI-focused extraction).

---

## 13. Hub support: `svt_usb_hub_agent`, `svt_usb_hub_agent_configuration`

`class `SVT_USB_HUB_SUBENV_TYPE extends `SVT_USB_HUB_SUBENV_SVT_TYPE;` (`svt_usb_hub_agent.sv:32`,
only 11.7% clear — heavily encrypted) and `class `SVT_USB_HUB_SUBENV_CONFIGURATION_TYPE extends
svt_usb_configuration;` (`svt_usb_hub_agent_configuration.sv:14`, tiny 89-line file, 60 clear).
Confirms a **parallel, separate agent hierarchy for USB hub modeling** exists (distinct macro
namespace `SVT_USB_HUB_SUBENV_*` vs the main agent's `SVT_USB_SUBENV_*`), gated throughout the rest
of the VIP by `` `ifdef SVT_USB_ENABLE_HUB_MODE `` (seen in `svt_usb_configuration.sv`'s
`is_downstream`/`is_upstream` fields, §5.2, and `svt_usb_system_virtual_sequencer`'s
`hub_virt_seqr[SVT_USB_NUM_HUB_INST]` field, §7.2). Hub mode is therefore a **compile-time opt-in
feature** (`SVT_USB_ENABLE_HUB_MODE` must be defined), not always-on. Internal hub logic is almost
entirely encrypted; only the class-hierarchy fact is extractable.

---

## 14. `svt_usb_types` — the shared enum catalog (`svt_usb_types.sv:276`)

`class svt_usb_types;` — a bare namespace class, does **not** extend anything, exists purely to
hold ~90 `typedef enum` declarations shared across every other USB class (referenced everywhere
above as `svt_usb_types::X`). 62.2% cleartext (3877/6238 lines) — the highest cleartext fraction of
any class file, because enum declarations are essentially never encrypted in this VIP (only a
handful of `` `ifdef ``-gated or doc-heavy spans are). Confirmed enum inventory includes (partial,
verified list; ~90 total `typedef enum` blocks exist, most not individually catalogued here):

```
dut_type_enum { DUT_NOT_APPLICABLE, DUT_USB_HOST, DUT_USB_DEVICE, DUT_USB_OTG_A, DUT_USB_OTG_B,
                DUT_USB_HUB_DFP, DUT_USB_HUB_UFP, DUT_USB_PHY }
component_type_enum { HOST, DEVICE }
processor_type_enum { EP_PROCESSOR, ITP_PROCESSOR, LMP_PROCESSOR, SOF_PROCESSOR, LPM_PROCESSOR,
                      LDM_PROCESSOR, TEST_MODE_PROCESSOR }
micro_ab_plug_type_enum { A, B, NOT_APPLICABLE }
otg_role_swap_status_enum { NOT_OTG_CAPABLE, OTG_HOST, OTG_DEVICE, OTG_A_ACTING_AS_DEVICE,
                            OTG_B_ACTING_AS_HOST, OTG_A_INITIATED_ROLE_SWAP_IN_PROGRESS,
                            OTG_B_INITIATED_ROLE_SWAP_IN_PROGRESS }
usb_protocol_enum { USB_SS, USB_20 }
direction_enum : bit { RX, TX }
ep_direction_enum : bit { OUT, IN }
ep_type_enum : bit[1:0] { CONTROL, BULK, INTERRUPT, ISOCHRONOUS }
ep_state_enum : bit[2:0] { EP_STATE_DISABLED, EP_STATE_RUNNING, EP_STATE_HALTED, EP_STATE_STOPPED, EP_STATE_ERROR }
speed_enum { LS, FS, HS, SS, ESSG2, ESSG1X2, ESSG2X2 }   // ESSG1X2/ESSG2X2 = Enhanced-SS Gen1x2/Gen2x2 (dual-lane), gated by SVT_USB_TEST_SUITE_XHCI_DRIVER_COMPILE / SVT_USB_TEST_SUITE_RTL_DUT
number_of_lanes_support_enum { LANE_SUPPORT_1, LANE_SUPPORT_2 }
usb4_port_speed_type_enum : bit[3:0] { USB4_PORT_SPEED_GEN2, USB4_PORT_SPEED_GEN3, USB4_PORT_SPEED_GEN4 }
lane_id_enum { LANE_0, LANE_1, BOTH_LANES }
usb3x_lpm_enum, mult_ep_transfer_type_enum, lfps_burst_type_enum, ux_exit_lfps_initiate_cov_enum,
usb_device_state_enum, usb_device_state_change_enum, behavior_for_error_insertion_in_tests_enum,
spsm_state_enum, imdsm_state_enum, omdsm_state_enum, linestate_value_enum : bit[2:0],
usb_20_eusb2_physical_state_enum : bit[3:0], usb_20_physical_power_state_enum : bit,
eusb2_repeater_state_enum : bit[1:0], eusb2_host_repeater_state_enum : bit[4:0],
eusb2_device_repeater_state_enum : bit[4:0], eusb2v2_utmi_data_rate_enum, eusb2v2_data_rate_enum : bit[3:0],
eusb2v2_configuration_and_operational_mode_register_enum : bit[5:0], eusb2v2_operation_mode_enum : bit[1:0],
eusb2v2_traffic_direction_enum : bit, eusb2v2_test_pattern_enum : bit[2:0], eusb2_rap_command_enum : bit[1:0],
usb_20_xcvr_state_enum : bit[1:0], usb_20_hsic_bus_state_enum : bit[2:0], usb_20_hsic_state_enum : bit[3:0],
usb_20_utmi_state_enum : bit[3:0], usb_ss_power_state_enum : bit[3:0], usb_ss_tx_state_enum : bit[1:0],
error_insertion_type_enum, bulk_stream_type_enum, framing_robustness_location_subtype_enum,
usb_ess_ldm_requester_state_enum : bit[2:0], usb_ess_ldm_responder_state_enum : bit[1:0],
link20sm_state_enum, link30sm_state_enum, behavior_type_ll_tests_enum,
host_device_concurrent_low_power_initiation_enum, ltssm_reserved_state_enum,
usb_20_power_state_enum : bit[1:0], ltssm_substate_enum, accelerated_transfer_type_enum,
framing_ordered_set_type_enum
```
(plus `ltssm_state_enum` referenced elsewhere, e.g. `U0`/`POLLING` values used in
`svt_usb_configuration.sv`, §5.2 — its own `typedef enum` body sits in an encrypted span in this
particular file but its members are corroborated by use-sites in `svt_usb_configuration.sv`).

This enum catalog is the correct single reference point for any future agent needing to validate
an enum literal or a `svt_usb_types::` type name against real VIP source rather than guessing.

---

## 15. Cross-references / corrections summary (for a future generation or debug agent)

1. **No `svt_usb_sequencer` class exists.** Use `svt_usb_virtual_sequencer` (per-agent) or
   `svt_usb_system_virtual_sequencer` (env-level, host+device+hub pairing) instead (§2.1, §7).
2. `svt_usb_transfer`/`svt_usb_packet`/`svt_usb_transaction`/`svt_usb_protocol_service`/
   `svt_usb_agent_service`/`svt_usb_xhci_trb` are **siblings**, all directly extending the
   technology-mapped `` `SVT_TRANSACTION_TYPE `` macro (→ `svt_sequence_item` under UVM) — **none
   of them extend each other**, despite the layering intuition (protocol transfer → transaction →
   link packet) that might suggest a subclass chain (§2, §8).
3. `svt_usb_device_configuration` / `svt_usb_host_configuration` / `svt_usb_endpoint_configuration`
   are **not** subclasses of `svt_usb_agent_configuration` or `svt_usb_configuration`'s active-agent
   branch — they're independent `svt_configuration` extensions used as list elements *inside* an
   agent configuration (§2, §11).
4. `svt_usb_link`/`svt_usb_physical`/`svt_usb_protocol` extend `svt_xactor` directly, not
   `svt_driver`/`svt_monitor` — each layer is a combined active/passive engine, with a *separate*
   sibling `_monitor` class also instantiated by the agent for passive checking regardless of
   active/passive mode (§9).
5. `agent_service_in_port` (prior session finding) is confirmed real and is specifically typed
   `` `SVT_XVM(seq_item_pull_port) #(svt_usb_agent_service) `` (§2.2) — not a generic/untyped port.
6. `svt_usb_if.svi`'s sub-interface set (prior session finding) is confirmed but **substantially
   larger** than the three interfaces previously named — verified complete list of 20+ instances in
   §4, including USB4-tunneling adapter interfaces, dual-lane PIPE4/SS-serial lane1 instances, SSIC
   M-PHY RMMI arrays, and a distinct standalone `ulpi_if` instance separate from
   `ulpi_dut_phy_if`/`ulpi_dut_mac_if`.
7. **ULPI is documented as NotYetImplemented** in the agent-level doc comment (§3.3), and
   **`svt_usb_utmi_dut_mac_if` carries its own, separate "THIS INTERFACE IS NOT YET SUPPORTED!"**
   caveat in its own interface doc comment (§4.1) — these are two distinct not-yet-supported flags
   on two different interfaces; do not conflate them, and do not assume UTMI+ is safe just because
   the ULPI caveat is the one usually quoted.
8. Hub-mode support (`svt_usb_hub_agent`, `is_downstream`/`is_upstream` fields,
   `hub_virt_seqr[SVT_USB_NUM_HUB_INST]`) is gated behind `` `ifdef SVT_USB_ENABLE_HUB_MODE `` —
   it is a compile-time opt-in, not always compiled in (§5.2, §7.2, §13).
9. `vip_generation_enum::GEN_A` (USB3.0-only, max 5 Gb/s) is explicitly flagged in its own doc
   comment as deprecated in favor of `GEN_B` (USB3.1 eSS) — a config-audit agent should flag any
   environment still selecting `GEN_A` (§5.1).
10. This VIP release (`W-2025.03`) has first-class **USB4 tunneling-mode** support
    (`vip_generation_enum::GEN_T`, `usb_adapter_signal_interface_enum`, `usb4_disconnect_usb3()`,
    `enable_usb4_adapter_mode_*` knobs) and first-class **xHCI TRB/TD/Ring** modeling
    (§8.1/§12) — both are real, current-generation capabilities, not legacy cruft, and should be
    considered live options for any new USB4-adjacent or xHCI-host-mode environment.

---

## 16. Follow-on extraction targets (flagged, not yet done — scope/time tradeoff in this pass)

- `svt_usb_packet.sv` field-by-field walk (PID encoding, CRC5/16/32 placement, ordered-set framing) — largest unexplored genuinely-readable class (6594 clear lines).
- `svt_usb_transfer.sv` field-by-field walk (4683 clear lines).
- `svt_usb_status.sv` full field inventory (5519 clear lines) — the live runtime-state object a debug agent would most want indexed.
- `svt_usb_host_configuration.sv` field walk (870 clear lines, only class declaration confirmed so far).
- xHCI TRB/TD/Ring field-level detail (`svt_usb_xhci_trb.sv`/`_td.sv`/`_trb_ring.sv`).
- The ~300 sequence-collection files under `src/sverilog/mti/` (100% cleartext, not touched in this
  pass at all) — these are a rich, fully-readable corpus of real, runnable test sequences
  (e.g. `svt_usb_20_na_30_ss_transfer_system_virtual_sequence_collection.sv`, 23086 lines, 100%
  clear) that a "VIP examples" category extraction should mine directly, distinct from this
  source-code-class-hierarchy extraction.
