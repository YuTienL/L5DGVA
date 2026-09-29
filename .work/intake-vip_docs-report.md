# VIP Docs Deep Extraction — Synopsys USB VC VIP (Category 1)

Scope: deep content extraction (not an index) of the real USB VIP documentation at
`D:\DV\Task\USB\VIP\doc\`, focused on what a generation/debug agent needs to integrate this VIP
as **Host** against **this project's DUT, which is confirmed Device-mode**
(`udc_DWC_usb31_params.svh`: `MODE=0`, `GCTL.PrtCapDir=Device`). Every fact below is cited to file
+ line number in the `.txt` companion of the PDF actually read.

Sources read in full or by targeted section (all under `D:\DV\Task\USB\VIP\doc\`):
- `usb_svt_uvm_user_guide.txt` (8828 lines) — primary UVM reference, v T-2022.09
- `usb_svt_hdl_user_guide.txt` (5910 lines) — HDL/command-interface reference, same VIP release
- `usb_svt_uvm_getting_started.txt` (646 lines) — **byte-for-byte identical** to `gs.txt` (diff = 0 lines; confirmed via `diff`)
- `faq.txt` (1689 lines) — full FAQ, sectioned by USB 2.0 / USB 3.0 / USB 3.1
- `perf.txt` (198 lines) — Verdi performance-metrics reference (short, read in full)
- `.pdf` originals exist alongside each `.txt` but were not opened (task instructed reading `.txt`)

---

## 1. Configuration object hierarchy

### 1.1 Canonical class hierarchy (UVM guide §4.2.3.1, lines 1874–1948; HDL guide §4.4/§4.4.2, lines 2517–2682)

All configuration objects derive from `svt_configuration` → `uvm_sequence_item`. The HDL guide states
the ordering explicitly (line 2519–2541, "Configuration objects are ordered hierarchically — lower
level objects must be referenced through a handle specified in a higher level object"):

```
svt_configuration                              (base, extends uvm_sequence_item)
 └─ svt_usb_configuration                      (protocol-agnostic USB config: capability, speed,
                                                 usb_ss_signal_interface, usb_20_signal_interface,
                                                 usb_capability, usb_ss_initial_ltssm_state, ...)
     └─ svt_usb_agent_configuration            (top-level cfg passed to svt_usb_agent via config_db;
                                                 adds testbench-capability enable flags: tracing,
                                                 exceptions, coverage; also carries host/device sub-cfgs)
         ├─ svt_usb_host_configuration         (host-role fields; protocol layer uses it to break
                                                 transfers into transactions)
         ├─ svt_usb_device_configuration       (device-role fields; collapses USB Device/Config/
                                                 Interface descriptor info into one object)
         │    └─ svt_usb_endpoint_configuration[]   (per-endpoint: ep_number, direction, ep_type,
         │         │                                  max_burst_size, max_packet_size, supports_ustreams)
         │         └─ svt_usb_ustream_resource_configuration   (SS bulk-stream resource info, only if
         │                                                       endpoint supports_ustreams)
```

HDL guide (§4.4.2.1–4.4.2.4, lines 2585–2682) gives the identical hierarchy but reached through the
command interface: `svt_usb_configuration` / `svt_usb_subenv_configuration` are the two top handles
obtainable directly; `svt_usb_device_configuration`/`svt_usb_host_configuration` are reachable only
via `get_data_prop` on the subenv config; `svt_usb_endpoint_configuration` only via `get_data_prop`
on a device config; `svt_usb_ustream_resource_configuration` only via `get_data_prop` on an endpoint
config. This is the **same object graph**, just walked through handles instead of `.` field access —
important if any part of this project's flow is HDL/command-interface based rather than pure UVM.

### 1.2 Key fields actually used to stand up the topology (UVM guide §5.4, lines 4715–4762; GS guide §2.1.2, lines 311–447)

For **"USB VIP Host and DUT Device"** (exactly this project's topology — VIP=Host, DUT=Device,
serial interface, no PIPE3/no remote PHY), two parameter sets are documented side by side
(UVM guide lines 4738–4761):

SS-only serial bus:
```
svt_usb_types::component_type_enum component_type = svt_usb_types::HOST;
svt_usb_types::speed_enum speed = svt_usb_types::SS;
component_subtype_enum component_subtype = MAC;
usb_ss_signal_interface_enum usb_ss_signal_interface = USB_SS_SERIAL_IF;
usb_capability_enum usb_capability = USB_SS_ONLY;
svt_usb_device_configuration remote_device_cfg[$];
svt_usb_endpoint_configuration endpoint_cfg[$];
int unsigned num_endpoints = 1;
int remote_device_cfg_size = 1;   // must be >= 1
```

2.0-only serial bus (HS, "other speeds FS/LS" per the doc):
```
svt_usb_types::component_type_enum component_type = svt_usb_types::HOST;
svt_usb_types::speed_enum speed = svt_usb_types::HS;      // or FS / LS
component_subtype_enum component_subtype = MAC;
usb_20_signal_interface_enum usb_20_signal_interface = USB_20_SERIAL_IF;
usb_capability_enum usb_capability = USB_20_ONLY;
svt_usb_device_configuration remote_device_cfg[$];
svt_usb_endpoint_configuration endpoint_cfg[$];
int unsigned num_endpoints = 1;
int remote_device_cfg_size = 1;   // must be >= 1
```
**Gotcha**: because the VIP is the Host and the DUT is the Device, the *host* config must carry a
fully populated `remote_device_cfg[$]` describing the DUT's endpoints (UVM guide line 438: "The USB
host configuration must include the configuration of a USB device that the host is communicated
with. Hence, the remote_device_cfg is constructed."). This is not optional boilerplate — omitting or
under-sizing `remote_device_cfg_size` breaks the topology.

GS guide (lines 350–431) gives a complete worked `usb_shared_cfg` example wiring `host_cfg` +
`host_cfg.remote_device_cfg[0]` + `host_cfg.remote_device_cfg[0].endpoint_cfg[0]` field-by-field,
including `SVT_USB_SS_CONTROL_MAX_PACKET_SIZE` macro for control-endpoint MPS and
`connected_bus_speed`/`functionality_support` fields that must match the DUT's actual negotiated
speed.

### 1.3 Runtime access/reconfiguration pattern (UVM guide §4.2.3.1 lines 1907–1917; FAQ §1.4–1.5 lines 366–434)

- Config is built in `test`/`env` `build_phase`, pushed via `uvm_config_db`, and the agent's
  `build_phase` retrieves it. **Static** config fields are read only between construction and
  `run_phase` start (or after a hard reset before start); **dynamic** fields (e.g. timeouts) can
  change any time.
- Post-construction reconfiguration is via `agent.reconfigure(cfg)` (one-arg method) — FAQ §1.5
  (lines 393–434) shows the canonical 3-step pattern: `get_cfg()` → `$cast` to
  `svt_usb_agent_configuration` after `.clone()` → mutate → `env.device_agent.reconfigure(vip_agent_cfg)`.
  Concrete example given: updating `local_device_cfg[0].device_address` **inside a
  `transfer_ended` callback** upon seeing a `SET_ADDRESS` control transfer — i.e. the standard way
  a Device-role VIP tracks USB enumeration address assignment.
- Also documented: `svt_usb_general_agent_service_sequence` with `service_type ==
  svt_usb_agent_service::REFRESH_CFG` run against `agent_service_sequencer`, paired with
  `svt_config_object_db#(svt_usb_agent_configuration)::set(...)` (FAQ §1.4, lines 366–388) — this is
  the sequence-based reconfiguration path, distinct from calling `.reconfigure()` directly.
- `static_rand_mode(bit on_off)` toggles static-field randomization as a block
  (UVM guide line 1904).
- Config Creator tool (`vipcc`) can produce a `.cfg` file loaded via `svt_data`'s
  `load_prop_vals(filename)` on an `svt_usb_agent_configuration` instance, validated with
  `is_valid(0)` (UVM guide §6.3, lines 5076–5124). Plusarg-driven runtime overrides use
  `set_prop_val_via_plusargs("KEYWORD")` (FAQ §1.3, lines 301–321) — e.g.
  `+DEV_CFG="enable_prot_xml_gen:1,inject_idle_cnt:1"`.

---

## 2. Agent / environment / component class hierarchy

### 2.1 UVM-side (UVM guide §4.2.1–4.2.3, lines 1789–2176; GS guide §2.1, lines 155–190)

```
uvm_agent (base)
 └─ svt_usb_agent            — top-level, one agent models a Host, Device, or Hub
      ├─ sequencer            (TLM pull-port export; USB xactor drivers pull via
                                sequence_item_pull_port)
      ├─ driver
      └─ monitor
```
A **USB environment** (`usb_basic_serial_env` in the GS example, line 318) is a user-defined UVM env
that "implicitly constructs the required number of USB host and USB device agents as specified by
its system configuration object" (GS guide line 163–166).

### 2.2 Internal transactor/layer stack shared by UVM and HDL flavors (UVM guide §1.1 lines 291–309; HDL guide §3.1.1 lines 571–617)

Both flavors of the VIP are built from the **same 3-layer stack**, just wrapped differently
(uvm_component in UVM mode, HDL "transactor" module in HDL/command mode):

```
svt_usb_physical   — physical layer (drives PIPE3 / serial signaling)
svt_usb_link       — link layer (LTSSM for SS; USB2.0 reset/suspend/resume state machines)
svt_usb_protocol   — protocol layer (breaks transfers into transactions/packets)
```
HDL guide additionally names a 4th, optional **remote_phys** transactor used only in
PIPE3-to-DUT-PHY topologies (not this project's topology, since §5.4 uses a plain serial
interface with no remote PHY — HDL guide §3.1.1, lines 597–607). Stack order top→bottom is
`prot → link → phys [→ remote_phys]`; the top transactor is selectable via the config
`top_xactor` property (HDL guide line 608–613) — i.e. a testbench can drive the VIP at the link
or physical layer directly, bypassing protocol-layer packing, if it sets `top_xactor` accordingly.

### 2.3 Concrete sub-component class names (verbosity sub-unit table, UVM guide §6.1.2.2, lines 5002–5047)

This table is effectively the real internal class hierarchy beneath `svt_usb_agent`, useful for
targeted `+uvm_set_verbosity`/`+vip_verbosity` debug and for recognizing class names in stack traces:

| Layer | Concrete classes |
|---|---|
| Whole agent | `svt_usb_agent` |
| Protocol – SS | `svt_usb_protocol`, `svt_usb_protocol_block`, `svt_usb_protocol_device`, `svt_usb_protocol_processor`, `svt_usb_protocol_ss_host`, `svt_usb_protocol_ss_host_non_isoc_ep_processor`, `svt_usb_protocol_ss_host_isoc_ep_processor`, `svt_usb_protocol_ss_device`, `svt_usb_protocol_ss_device_non_isoc_ep_processor`, `svt_usb_protocol_ss_device_isoc_ep_processor`, `svt_usb_protocol_scheduler`, `svt_usb_protocol_host_scheduler`, `svt_usb_protocol_device_scheduler`, `svt_usb_protocol_ss_lmp_processor`, `svt_usb_protocol_ss_itp_processor` |
| Protocol – 2.0 | `svt_usb_protocol_processor`, `svt_usb_protocol_20_host_non_isoc_ep_processor`, `svt_usb_protocol_20_host_isoc_ep_processor`, `svt_usb_protocol_20_device_non_isoc_ep_processor`, `svt_usb_protocol_20_device_isoc_ep_processor`, `svt_usb_protocol_block`, `svt_usb_protocol_20_host`, `svt_usb_protocol_20_device`, `svt_usb_protocol_20_lpm_processor`, `svt_usb_protocol_20_sof_processor` |
| Link – SS | `svt_usb_link_ss_tx`, `svt_usb_link_ss_rx`, `svt_usb_link_ss_ltssm_base`, `svt_usb_link_ss_lcm` |
| Link – 2.0 | `svt_usb_link_20`, `svt_usb_link_20_device_a_sm`, `svt_usb_link_20_device_b_sm`, `svt_usb_link_20_timer` |
| Physical | `svt_usb_physical` |

**Device-mode-relevant**: since the DUT is a Device, the active protocol processor classes on the
VIP (Host) side for endpoint traffic are `svt_usb_protocol_20_host_non_isoc_ep_processor` /
`svt_usb_protocol_20_host_isoc_ep_processor` (2.0/HS-FS-LS) and/or
`svt_usb_protocol_ss_host_non_isoc_ep_processor` / `_isoc_ep_processor` (SS), matched against
`svt_usb_link_20_device_a_sm`/`_b_sm` link-layer state machines — see §2.2.3 next.

### 2.4 USB 2.0 link-layer state-machine naming — VIP-side "A-device"/"B-device" (FAQ §2.2.3, lines 1061–1099)

The VIP's own default logging identifies its USB2.0 link state machine role by search string:
- **`L20_DEV_A_SM`** — printed when "VIP acting as A-Device (Host in non-OTG mode)". Example log:
  `uvm_test_top.env.host_agent.link.usb_20_device_a [device_attached] L20_DEV_A_SM: DEVICE_ATTACHED <- DISCONNECTED`
  then `... DEVICE_ATTACHED -> RESETTING`.
- **`L20_DEV_B_SM`** — printed when "VIP as B-Device (Device in non-OTG mode)". Example:
  `uvm_test_top.env.dev_agent.link.usb_20_device_b [receiving_is_state] L20_DEV_B_SM: RECEIVING_IS <- BUS_RESET`

Since this project's VIP instance is configured as Host (`component_type = HOST`), grepping sim logs
for `L20_DEV_A_SM` is the concrete debug hook for USB2.0 link-layer state transitions
(DISCONNECTED → DEVICE_ATTACHED → RESETTING → ...) when chasing a device-mode enumeration/reset bug.

### 2.5 UVM base classes actually used (UVM guide §4.2.1, lines 1799–1806)

`uvm_agent`, `uvm_component`, `uvm_object`, `uvm_callback`, `uvm_sequencer` — the VIP does not
invent its own component-model primitives; all extension is standard UVM inheritance.

### 2.6 HDL module types (non-UVM flavor — relevant if any BFM/command.txt layer wraps this VIP) (HDL guide §3.1.6, lines 1903–2032+)

Seven `.sv` module files are shipped, differentiated by port-interface combination:
`svt_usb_subenv_pipe3_plp_hdl.sv`, `svt_usb_subenv_20_serial_pipe3_plp_hdl.sv`,
`svt_usb_subenv_ss_serial_plp_hdl.sv`, `svt_usb_subenv_20_serial_plp_hdl.sv`,
`svt_usb_subenv_20_serial_ss_serial_plp_hdl.sv`, `svt_usb_subenv_20_serial_pipe3_plpr_hdl.sv`,
`svt_usb_subenv_pipe3_plpr_hdl.sv`. Each PLP ("protocol-link-physical") module provides a 3-element
stack with protocol/link optional and physical required; port interface (PIPE3 vs SS-serial vs
2.0-serial vs both) picks the module. For this project's exact topology (VIP Host, serial interface,
DUT Device, no PIPE3), the applicable HDL module for 2.0/HS traffic is
**`svt_usb_subenv_20_serial_plp_hdl.sv`** (or `..._ss_serial_plp_hdl.sv` for SS, or
`..._20_serial_ss_serial_plp_hdl.sv` for concurrent SS+2.0).

---

## 3. Sequence library organization

### 3.1 Base sequence classes (GS guide §2.1.3, lines 499–516)

> "The VIP provides a base sequence class for the USB host agent (`svt_usb_host_base_sequence`) and
> the USB device agent (`svt_usb_device_base_sequence`). You can extend these base sequences to
> create test sequences for the USB host and device agents."

Device response sequences must be armed explicitly: **"You must set a device response sequence for
active devices in the run phase"** (GS guide line 515) — a documented gotcha: an active Device-role
agent will not auto-respond without a sequence started on it, so if this project ever instantiates a
passive/active device-side monitor agent alongside the Host VIP, forgetting to start a default
sequence on its `xfer_sequencer` in `run_phase`/`main_phase` will silently hang or NAK all transfers.

Sequences are wired via the standard UVM factory default-sequence mechanism (GS guide lines 525–526):
```
uvm_config_db#(uvm_object_wrapper)::set(this,
  "env.host_agent.xfer_sequencer.main_phase",
  "default_sequence", usb_bulk_out_bulk_in_random_sequence::type_id::get());
```
`usb_bulk_out_bulk_in_random_sequence` is the concrete example sequence named — it lives in the
example area, not in the VIP's own class hierarchy (per-example sequences vs. VIP-shipped base
classes are two different things).

### 3.2 VIP-internal sequence naming convention for scenario/error sequences (FAQ §3.1.4, lines 1273–1305; §6.5.2, UVM guide lines 8063–8075)

The FAQ gives a direct answer key of built-in scenario **system virtual sequences**, which reveals
the naming grammar:
```
svt_usb_<layer-or-scope>_<speed-combo>_<scenario>_system_virtual_sequence
```
Concrete examples pulled verbatim from the FAQ:
- Disparity error: `svt_usb_20_na_30_ss_link_errors_received_dpp_10_bit_disparity_error_system_virtual_sequence`
- CRC-5 error: `svt_usb_20_hs_fs_30_na_bulk_in_crc5_error_system_virtual_sequence`
- CRC-16 error: `svt_usb_20_hs_fs_30_na_bulk_in_crc16_error_system_virtual_sequence`
- HSEQ# mismatch: `svt_usb_20_na_30_ss_link_errors_rx_hp_hseq_and_rx_hdr_seq_num_mismatch_error_system_virtual_sequence`
- CRC-32 error: `svt_usb_20_na_30_ss_bulk_in_dpp_crc32_error_system_virtual_sequence`
- DPP abort: `svt_usb_protocol_service_abort_current_transfer_sequence` (run on the **protocol
  service sequencer**, not a data sequencer — different sequencer than transfer sequences)
- DPP missing: `svt_usb_20_na_30_ss_bulk_out_invalid_dpp_due_to_dpp_missing_random_endpoint_system_virtual_sequence`

The `20_hs_fs` / `20_na_30_ss` / `30_na` infixes encode which speed grades (2.0 HS/FS vs 3.0 SS, "na"
= not-applicable to that half) the scenario exercises — i.e. **error scenarios are pre-baked per
speed combination**, so when this project's DUT is 2.0-only (HS/FS/LS device mode with no SS), only
the `20_hs_fs_30_na_*` family (or plain `20_*`) is applicable; the `*_30_ss_*`/`*_ss_*` sequences
target SuperSpeed link errors that do not apply to a 2.0-only device integration.

For "normal" (non-error) built-in coverage-driving sequences, the naming is simpler, e.g.
`svt_usb_ack_dp_packet_sequence` (normal ACK-DP behavior) vs.
`svt_usb_invalid_ack_no_response_packet_sequence` (error-condition counterpart) — UVM guide
§6.5.2.1/6.5.2.2 (lines 8063–8075). This confirms a **two-tier split**: "normal behavior sequences"
(no error) and "error condition sequences" (error injected), each independently coverage-crossed
against packet-field-range coverpoints.

### 3.3 High-level Verification Plan (HVP) naming (UVM guide §6.5.7, lines 8287–8298)

Top-level plans: `svt_<suite>_<operation_mode>_dut_<protocol_mode>_toplevel_fc_plan`
Sub-plans: `svt_<suite>_<vip_layer>_<protocol_mode>_<transfer_type>`
Located at `$DESIGNWARE_HOME/vip/svt/usb_svt/<version>/doc/VerificationPlans` — useful for locating
the plan matching "host-dut-device" `operation_mode`/`dut` combination that matches this project.

### 3.4 Example testbenches as a sequence source (UVM guide §6.2, lines 5054–5074; GS guide line 189)

`tb_usb_svt_uvm_basic_sys` (SS-serial basic example: top TB + Verilog interconnect + host/device
agents + one sequence + two directed tests) and `tb_usb_svt_uvm_intermediate_sys` (adds coverage +
scoreboard) are the two SystemVerilog-UVM example dirs documented. GS guide explicitly points at
`examples/sverilog/tb_usb_svt_uvm_basic_sys` as the reference for all its code snippets (line 189).

---

## 4. Callback mechanism

### 4.1 Architecture (UVM guide §4.2.2 lines 1823–1848, §4.2.3.5 lines 2122–2176)

- Callback facade classes are associated **per sequencer/component**; a user extends the facade and
  registers an instance via the standard UVM callback-pool API:
  `uvm_callbacks#(svt_usb_protocol)::add(my_agent.prot, my_20_dev_resp_cb);`
- Callbacks are **virtual, empty by default** — "There is no need to invoke callback methods for
  callbacks that are not extended. To avoid a loss of performance, callbacks are not executed by
  default" (line 2151) — i.e. zero runtime cost unless registered, and functional-coverage callback
  methods are the one documented exception (they ship a default coverage implementation).
- Three callback classes are defined by the VIP: `svt_usb_link_callbacks`,
  `svt_usb_physical_callbacks`, `svt_usb_protocol_callbacks` (line 2170–2173).
  `svt_usb_protocol_callbacks` (the one used in essentially every documented example) extends
  `svt_xactor_callbacks` → `uvm_callback` (line 2129–2131).
- Three callback *categories* by call site: **post-port-get** (after pulling a txn off an input
  port), **pre-port-put** (before pushing a txn to an output port), and **traffic/dataflow event**
  callbacks (fired on protocol events, can inject errors) — line 2162–2168.
- Coverage callbacks are a special case: they run *after* the corresponding get/put method
  **unless** that method set `drop_it = 1` (line 1846–1848) — so a callback that drops a transaction
  suppresses its own coverage sample.

### 4.2 Concrete callback method inventory actually named in the doc (UVM guide §4.2.9, lines 3095–3556)

All on `svt_usb_protocol_callbacks` unless noted:
- `post_transfer_in_port_get(component, port_id, transfer, ref bit drop)` — called right after a
  transfer is pulled off `transfer_in`; setting `drop=1` here skips coverage collection for it.
- `transfer_in_port_cov(component, port_id, transfer)` — coverage sample point, only reached if
  `drop` was false above.
- `randomized_transaction(component, transfer, transaction_ix, protocol_randomization_point_enum
  rand_point)` — fired every time the VIP randomizes a transaction's `host_response` (Host role) or
  `device_response` (Device role) via the `randomized_usb_20_transaction`/`randomized_usb_SS_...`
  factory field. **This is the documented hook for overriding response behavior** — FAQ §3.1.6
  (lines 1312–1350) shows a full worked example (`retry_ack_callback`) that inspects
  `xact.last_pkt_sent.tp_subpacket_type`/`.rty_bit` and mutates
  `xact.rty_bit_0_in_resend_of_ack_after_retry_ack` inside this callback.
- `received_data_packet(component, transfer, packet)` — fired when an error-free DATA packet is
  received for the transfer (both Host-receiving-IN and Device-receiving-OUT/SETUP paths call this).
- `transaction_ended(component, transfer, transaction_ix)` — end-of-transaction-loop callback,
  separate from the per-transaction `NOTIFY_USB_TRANSACTION_ENDED` uvm_event trigger.
- `transfer_ended(component, transfer)` — fires once the whole transfer loop terminates (transfer
  `end_tr()` already called).
- `pre_usb_20_packet_out_port_put(component, chan_id, packet, transaction, packet_ix, transfer,
  transaction_ix, ref bit drop)` — pre-put hook for USB2.0 packets; the documented use is mutating
  `packet.payload.data[]` right before it leaves the protocol layer for the link layer (FAQ §1.22,
  lines 852–905, full worked `modify_ctrl_read_data_callback` example that patches a
  DEVICE_TO_HOST control-read response payload byte-by-byte based on
  `transfer.setup_data_bmrequesttype_dir`/`transfer.xfer_type`).
  A parallel `pre_usb_SS_packet_out_port_put()` exists for USB3.x packets (FAQ line 854, named but
  not detailed).

### 4.3 Full Host-role callback/event flow, non-isochronous (UVM guide §4.2.9.1.1, lines 3095–3244) — **this is the VIP's role in this project**

Transfer Start Phase: (1) VIP gets `transfer` from `transfer_in` port → (2) randomizes
`randomized_transfer_in_exception_list` and merges into `transfer.exception_list` → (3) calls
`post_transfer_in_port_get(...)` → (4) if `drop==0`, calls `transfer_in_port_cov(...)`.

Transfer Loop (repeats per transaction until transfer complete/aborted): create+process transaction
via the Transaction Loop, then on final iteration `transfer.end_tr()` followed by
`svt_usb_protocol_callbacks::transfer_ended(...)`.

Transaction Loop: (1) send TOKEN (+DATA/HANDSHAKE as needed) → (2) receive DATA/HANDSHAKE from
device if required → (3) branch by transaction type:
- **Device IN DATA response, error-free**: append payload → `received_data_packet(...)` →
  (non-CSPLIT) `transfer.payload.append_payload(packet.payload)` / (CSPLIT-last)
  `transfer.payload.append_payload(transaction.payload)` → on last-CSPLIT: `transaction.status =
  ACCEPT`, `transfer.end_tr()`, `NOTIFY_USB_TRANSACTION_ENDED.trigger(transaction.clone)`.
  Non-split: randomize `host_response` via `randomized_usb_20_transaction`, call
  `randomized_transaction(...)`; if `HOST_NORMAL_RESPONSE` re-enter Prepare/Send; if ACK with no
  injected errors, mark ACCEPT/end/trigger as above.
- **Device HANDSHAKE for OUT**: ACK or NYET (non-SPLIT/complete-SPLIT) both subtract
  `transaction.payload.byte_count` from `transfer.payload_bytes_remaining`, ACCEPT, `end_tr()`,
  trigger `NOTIFY_USB_TRANSACTION_ENDED`.
- **Device HANDSHAKE for SETUP**: same ACCEPT/end_tr/trigger pattern on ACK.
- **Max-error abort**: "If the transaction exceeds the maximum allowed number of errors, VIP aborts
  the transfer" — repeated verbatim after every branch; this is the universal error-budget cutoff.
- (4) loop back to top of Transaction Loop, or fire `transaction_ended(...)` once truly done.

Isochronous variant (§4.2.9.1.2, lines 3245–3346) is structurally identical but has no
retry/handshake-driven repeat semantics — IN DATA and OUT paths both terminate on
non-SPLIT/last-CSPLIT with the same ACCEPT/end_tr/`NOTIFY_USB_TRANSACTION_ENDED` triple, and OUT/NYET
handling mirrors the non-iso OUT-handshake path.

### 4.4 Device-role callback flow, for contrast (UVM guide §4.2.9.2, lines 3347–3556) — relevant only if this project ever adds a passive/loopback Device-role agent

Transfer starts when the Device VIP receives a TOKEN on `packet_in_port` (not a `transfer_in` port —
key structural difference from Host role, since a Device doesn't originate transfers, it responds to
them). Every transaction branch ("not SPLIT-OUT/SETUP", "START SPLIT", "Complete SPLIT OUT/SETUP",
"non-SPLIT IN", "Complete SPLIT IN (INTERRUPT)", "Complete SPLIT IN (BULK/CONTROL)") first calls a
**"Randomize Transaction for Response"** callback flow (this is where `device_response` gets set,
analogous to Host's `host_response`) before optionally sending/receiving a packet, then converges on
the same ACCEPT/`end_tr()`/`NOTIFY_USB_TRANSACTION_ENDED` pattern. FAQ §3.1.1/§3.1.2 point at
SolvNetPlus articles ("Modifying Device Data Responses", "USB 2.0 Device VIP Response Modification")
for concrete override recipes but do not inline the code in this local doc set.

### 4.5 HDL/command-interface callback mechanism (different mechanism from UVM callbacks!) (HDL guide §2.1.2, lines 417–463)

The HDL (non-UVM, command-based) flavor does **not** use `uvm_callback` registration at all — it uses
a synchronous handshake pair:
- `cmd_callback_wait_for(is_valid, out_handle, "prot.NOTIFY_CB_<event_name>")` — blocks until the
  named callback point, returns a data-object handle.
- `cmd_callback_proceed(...)` — the handshake ack that releases the VIP past that callback point.
- **Hard constraint**: "The testbench must not allow simulation time to advance while it accesses the
  data object obtained at a callback point. If simulation time is advanced between the
  `cmd_callback_wait_for` call and the `cmd_callback_proceed`... call, a fatal error is reported."
  (lines 434–437) — a zero-time critical section, structurally identical in spirit to the UVM
  callback's synchronous virtual-method call but enforced by a runtime fatal instead of by language
  semantics.
- Named example: `cmd_callback_wait_for(is_valid, callback_handle, "prot.NOTIFY_CB_NEW_SS_RESPONSE_TRANSFER")`.
- Use `cmd_callback_wait_for` in a loop (not `cmd_callback_proceed`) when multiple instances of the
  same callback can legitimately fire in one time step (e.g. simultaneous transaction completions).

---

## 5. Verification topologies — exact match for this project (UVM guide Ch. 5, lines 4565–4933; HDL guide Ch. 5, lines 4763–5133, structurally identical figures/tables)

Seven topologies are documented; **§5.4 "USB VIP Host and DUT Device"** (lines 4715–4762) is this
project's topology verbatim: VIP contains local protocol+link+physical emulating a Host; DUT is the
Device; connection is a **serial interface** (not PIPE3 — PIPE3 topologies are §5.1/§5.3 and target a
DUT *device controller* or DUT *PHY* respectively, not a full DUT device). The exact `cfg` field
settings for both SS-only and 2.0-only variants are reproduced in §1.2 above.

Contrast for completeness: §5.2/§5.5 ("USB VIP Device and DUT Host...") are the *mirror* topology —
NOT this project's case, but worth knowing to avoid copy-pasting the wrong example from a search hit,
since §5.2/§5.5 also mention `remote_device_cfg`/`remote_host_cfg` fields with similar-looking names
but opposite `component_type` (`DEVICE`) and a `remote_host_cfg` (singular, not a queue) instead of
`remote_device_cfg[$]`.

---

## 6. Physical/link-layer signaling gotchas specific to USB2.0 device-mode integration (FAQ §2, lines 1031–1252)

These are the highest-value, most concrete gotchas for this project's actual topology (2.0/HS-FS-LS
serial, VIP=Host, DUT=Device):

- **Clock requirement**: VIP requires a 4x-oversampled input clock for its serial interface
  regardless of role — "clock recovery is enabled by default. This requirement applies to all VIP
  operations regardless of the VIP's configuration as a USB host, device or hub" (GS guide lines
  283–285). For USB2.0 HS/FS/LS: **1.92 GT/s (4× 480 MT/s)** on `usb_20_serial_if.clk`
  (FAQ line 1140–1141, GS guide line 296–297). For SS: 20 GT/s (4× 5 GT/s) on `usb_ss_serial_if.ssclk`
  (GS guide line 287–288). GS guide gives a full clock-generation `initial`/`forever` block
  (lines 250–276) with the 8-phase duty-cycle pattern used for the SS example — same technique
  needed for the 2.0 clock at the 2.0 period.
- **SOF generation is OFF by default on the Host VIP** (FAQ §2.1.1, line 1037) — must be explicitly
  driven via `svt_usb_protocol_service` SOF Command over a service port/channel. If this project's
  DUT (Device) expects periodic SOF/keep-alive from the Host VIP and none appears, this is the first
  thing to check.
- **UTMI reset duration** is configurable: `dev_cfg.utmi_reset_duration = 1000;` (real attribute,
  default `SVT_USB_20_HS_FS_8_BIT_INTERFACE_UTMI_CLOCK_PERIOD*10`) — FAQ §2.2.4, lines 1100–1114.
- **VIP attachment delay** control via `svt_usb_configuration::poweron_auto_attach_delay` (real,
  default 0): `=0` → starts attached; `>0` → starts detached, auto-attaches after that delay; `<0` →
  starts detached and needs a manual `ATTACH_DEVICE` physical-service command (FAQ §2.2.5, lines
  1116–1134). Relevant if the DUT needs a specific VBUS/attach sequencing before reset.
- **DP/DM signal-strength model** (FAQ §2.3.2, lines 1143–1163): VIP drives HS strength as
  `supply`, FS/LS strength as `strong`, pull-down as `weak`, pull-up as `pull`, and declares the
  nets as `wor` (wired-or). Explicit warning: **"For proper simulation, the DUT/testbench is
  recommended to use the same set of criteria for modeling the DP/DM signals. If the set of criteria
  does not match the signaling criteria, then the simulation anomalies are reported."** This is a
  concrete, actionable integration check against the DUT's PHY model.
- **EOP tolerance mismatch** (FAQ §2.3.5, lines 1184–1191): VIP by default expects exactly 8 EOP
  bits and reports `UVM_ERROR` if the DUT sends more (which is spec-legal). Fix: compile-time macro
  `+define+SVT_USB_20_USER_MAX_HS_EOP_LENGTH=9` (also §2.3.10, lines 1244–1248, same macro reused
  for "change default EOP length" — same knob answers two FAQ entries).
- **Drive-strength override macros** if the wired-or model conflicts with the DUT's PHY model
  (FAQ §2.3.6, lines 1192–1204): six `SVT_USB_DRIVE_STRENGTH_USER_DEFINED_*` defines for
  PULLDOWN0/1, PULLUP0/1, HS_TERMINATION0/1.
- **Interface-not-bound fatal**: `UVM_FATAL remote_cfg specified with usb_20_signal_interface =
  UTMI_IF but usb_20_if not provided with the config db or remote_cfg.` Fix is a missing
  `uvm_config_db#(svt_usb_if)::set(this, "host_agent", "usb_20_if", this.host_usb_if);` (FAQ §2.3.3,
  lines 1164–1172) — a very literal "you forgot to bind the virtual interface" gotcha, easy to hit
  when refactoring agent instance names.
- **Timers relevant to 2.0 device-mode integration** (FAQ §2.3, multiple):
  - `Tdrsmdn` (host downstream resume duration), default `SVT_USB_TDRSMDN_MIN` (line 1178).
  - `Tdrsmup` (device upstream resume duration, **driven by the device VIP**), default `1ms`
    (line 1216) — relevant if this project ever exercises remote wakeup from the DUT.
  - `Tdrst` (host protocol-reset duration, i.e. bus-reset drive time), default `10ms` (line 1227).
  - Sync-length overrides: `cfg.dev_cfg.usb_20_hs_sync_length_min = 30`,
    `usb_20_fs_sync_length_min = 4`, `usb_20_ls_sync_length_min = 4` (lines 1238–1242) — note this is
    set on `dev_cfg`, i.e. the *simulated device's* sync field, applicable when the VIP itself is
    modeling a device (not this project's direct role, but relevant if a loopback/monitor Device
    agent is added).
- **Aligned-transfer termination semantics differ subtly by role** (UVM guide §6.4.2.1 vs §6.4.2.2,
  lines 5341–5457): with `allow_aligned_transfers_without_zero_length=0` (default) and an aligned
  payload, a Host-role VIP OUT transfer will *not* end with a zero-length DP unless
  `aligned_transfer_with_zero_length` is explicitly set to 1 on the transfer object — and if the
  endpoint config and the transfer's `aligned_transfer_with_zero_length` disagree, the VIP reports an
  "endpoint configuration and transfer attributes are inconsistent" **error** but still proceeds
  using the *endpoint config's* behavior, not the transfer's requested behavior. **Cross-reference
  contradiction worth flagging**: the table header row literally says "Table 6-18 describes the VIP
  behavior when it is acting as a host" (line 5404) directly under the "6.4.2.2 VIP Acting as a
  Device" heading — this is a copy-paste error in the source PDF/txt (the table content itself is
  clearly the Device-role behavior, mirroring the Host table with OUT/IN swapped), not a real VIP
  behavior discrepancy; flagged here so a future reader doesn't mis-cite table 6-18's caption.

---

## 7. Message/verbosity and error-budget mechanics (UVM guide §4.2.7 line 2401–2420, §6.1 lines 4933–5047; FAQ §1.10–1.13, §1.16, lines 482–605, 749–757)

- VIP↔UVM severity mapping: `` `svt_fatal``→`UVM_FATAL`, `` `svt_error``→`UVM_ERROR`,
  `` `svt_warning``→`UVM_WARNING`, `` `svt_note``/`` `svt_trace``/`` `svt_verbose``→`UVM_INFO`
  (FAQ table, lines 489–496).
- Per-class runtime debug: `+vip_verbosity=<class_name>:debug`, e.g.
  `+vip_verbosity=svt_usb_link_20_timer:debug` (FAQ §1.16, line 753–757) — direct instrument for
  debugging USB2.0 timer behavior (reset/suspend/resume durations from §6 above).
- Blanket verbosity: `+UVM_VERBOSITY=UVM_HIGH`; per-subunit: `+vip_verbosity=<unit>:<LEVEL>,...`
  against the sub-unit table reproduced in §2.3 above (UVM guide lines 4980–4986).
- Max UVM_ERROR count and HDL-mode max-error-count are both pointer-only in this FAQ (SolvNetPlus
  article titles named, no inline mechanism given) — FAQ §1.12/§1.13, lines 592–605.
- Trace files: per-layer/per-direction trace file naming convention
  `vip_agent.<xactor>.<speed>.<RX|TX>.<data|packet|transaction|transfer>_trace`, renamed via
  `set_filename(default_name, user_name)` on the corresponding
  `svt_usb_*_monitor_*_report_callback` object obtained by `$cast` off
  `agent.prot_xfer_report_cb` etc. (FAQ §1.11, lines 500–590) — six distinct report-callback class
  names enumerated: `svt_usb_protocol_monitor_transfer_report_callback`,
  `svt_usb_protocol_monitor_service_report_callback`,
  `svt_usb_protocol_monitor_transaction_report_callback`,
  `svt_usb_link_monitor_service_report_callback`, `svt_usb_link_monitor_packet_report_callback`,
  `svt_usb_physical_monitor_data_report_callback` (+ a remote-phy variant of the last).

---

## 8. Functional coverage class hierarchy (UVM guide §6.5, lines 7997–8299)

```
svt_pattern (protocol-layer sequence objects extend this)
svt_usb_pattern (link-layer sequence objects extend this)
   [these two are NOT part of the coverage class hierarchy proper — they just define
    the comparison patterns coverage matches against]

<component> coverage data callback   — naming: *_def_cov_data_callbacks
   └─ <component> coverage callback  — naming: *_def_cov_callbacks  (extends the data callback,
                                        adds the actual covergroups)
```
Naming grammar (line 8207): `svt_usb_<layer>_<speed>_<VIP config>_def_cov_<type>callbacks` where
`<layer>`∈{protocol,link,physical}, `<speed>`∈{ss,20}, `<VIP config>`∈{host,device},
`<type>`∈{`data_`, ``} (empty for the covergroup-bearing class). Concrete inventory table (lines
8228–8262) confirms both Host and Device variants exist independently per layer/speed, e.g.
`svt_usb_protocol_20_host_def_cov_data_callbacks` / `svt_usb_protocol_20_host_def_cov_callbacks` vs.
the `_device_` counterparts — since this project's VIP is Host-only, the `*_20_host_*` (and, if SS is
exercised, `*_ss_host_*`) pair is what actually accumulates coverage; the `*_device_*` pair only
matters if a Device-role monitor/agent is added.

Enable switches live on the agent config: `enable_prot_cov` (all protocol covergroups),
`enable_link_cov` (all link covergroups) — UVM guide lines 8273–8274. Coverpoints are split into 4
categories (Normal Behavior Sequences, Error Condition Sequences, Packet Field Range Coverpoints,
Data Collection Coverpoints — §6.5.2, lines 8056–8092) and crossed with `options.weight=0` on the
individual coverpoints inside a cross so only the cross itself scores (line 8116–8117) — a subtlety
that matters if this project ever audits raw coverage-model weighting.

---

## 9. Passive-monitor pattern (UVM guide §6.6, lines 8300–8363)

To attach the VIP purely as a **protocol checker/monitor** alongside/instead of an active DUT-facing
agent (both Host-monitor and Device-monitor variants documented, steps identical modulo naming):
1. Instantiate a normal `svt_usb_agent` (e.g. `dev_mon_agent`).
2. `uvm_config_db#(svt_usb_agent_configuration)::set(this,"dev_mon_agent","cfg", cfg.dev_cfg);` —
   config should mirror the real DUT's role config, not a fresh default.
3. **`uvm_config_db#(bit)::set(this,"dev_mon_agent","is_active", 0);`** — the actual "make it
   passive" switch.
4. Bind the virtual interface the same way as an active agent
   (`uvm_config_db#(USB_IF)::set(this,"dev_mon_agent","dev_ss_if", this.dev_usb_if);`).
Documented restriction: **"Passive Monitor support is not available for physical as top layer"**
(line 8363) — i.e. `top_xactor` must be protocol or link, not physical, for a passive monitor to
work. Also line 8306–8308: "It is recommended to set the configuration parameter with DUT" (i.e. the
monitor's cfg should track whichever side — host or device — the real DUT plays, not the VIP's own
active role).

---

## 10. Compile/runtime setup essentials (GS guide §2.2, lines 528–585; §2.1.1 lines 191–307)

- Required `+incdir+`: `.../include/sverilog` and `.../src/sverilog/<simulator>` (vcs/ncv/mti).
- Required compile defines: `+define+SVT_UVM_TECHNOLOGY`, `+define+UVM_PACKER_MAX_BYTES=24000`
  (or higher — **must be set to the max required by *any* VIP title compiled together**, line
  566–569), `+define+UVM_DISABLE_AUTO_ITEM_RECORDING`, `+define+SYNOPSYS_SV`.
- **Timescale gotcha**: "You must compile all VIP files with the timescale 1ps/1ps" (GS guide line
  207–209) — either a compile-time option or an explicit `` `timescale 1ps/1ps`` before including VIP
  files. Silent mistiming bugs are the likely failure mode if skipped.
- **Interface-file gotcha specific to UVM**: "In UVM the `svt_usb_if` interface comes from the
  `svt_usb_if.uvm.svi` file (as opposed to `svt_usb_if.svi`). This ensures that you obtain the
  correct interface: one which does not have parameters. Note that this is only for the top level
  interface." (UVM guide §4.2.4, lines 2214–2218) — picking the wrong `.svi` is a documented trap.
- No VIP-specific runtime plusargs are required beyond standard UVM ones
  (`+UVM_TESTNAME=<test>`) — GS guide §2.2.3, lines 579–585.

---

## 11. Cross-reference notes / contradictions observed between sources

1. **gs.txt ≡ usb_svt_uvm_getting_started.txt** — byte-identical (`diff` = 0 lines). Treat as one
   source; this report cites it as "GS guide" regardless of which filename is referenced elsewhere.
2. **UVM guide §5.x and HDL guide §5.x are structurally identical** (same 7 topologies, same figure
   numbers, same config field lists) — the HDL guide's chapter 5 is effectively a verbatim reprint
   of the UVM guide's chapter 5 with no HDL-specific reinterpretation of the topology diagrams
   (both show `cfg`/`remote_cfg` as UVM-style field assignments, not `set_data_prop` calls) — a
   reader expecting HDL-flavored topology examples (using `get_data_prop`/`set_data_prop`/
   `apply_data`) will not find them there; the command-interface examples live only in HDL guide
   Ch. 2–4 (general concepts + module configuration), not Ch. 5.
3. **UVM guide §6.4.2.2 table-caption bug**: "Table 6-18 describes the VIP behavior when it is
   acting as a host" appears directly under the "6.4.2.2 VIP Acting as a Device" heading (line 5404)
   — the table's actual content (OUT-continues-receiving / IN-continues-providing framing) is
   self-consistent with Device-role behavior, so this is almost certainly a copy-paste caption error
   in the source document, not a real behavioral claim to trust literally. Documented in §6 above so
   it isn't silently propagated as fact.
4. **FAQ's SolvNetPlus-only pointers**: several FAQ entries (§1.12, §1.13, §2.2.1, §2.2.2, §3.1.1,
   §3.1.2) give only an article *title* with no inline mechanism, because the actual answer lives on
   the Synopsys SolvNetPlus portal, not in this local doc set. These are recorded as "pointer only,
   no local detail" so a future agent doesn't assume the mechanism is fully documented here and
   doesn't waste time re-searching this same file for detail that isn't present.
5. **perf.txt is a distinct, narrow document** (Verdi-integrated performance-metrics reference only —
   ~30 named metrics, all SS/2.0 transfer-rate, LTSSM-transition-latency, and LFPS-timing counters).
   It has no overlap with configuration/callback/sequence material and should be treated as its own
   category (`programming_guide`/debug-metrics) rather than folded into the main VIP architecture
   narrative.

---

## 12. Directory/version metadata (FAQ §1.1, §1.14, lines 211–239, 606–693)

VIP install directory structure: `cc/` (Configuration Creator files), `pa/` (Protocol Analyzer
files), `examples/`, `sverilog/`/`Verilog/` (model sources), `Doc/`. Sub-package split under
`sverilog/src/<simulator>`: `usb_link_svt`, `usb_physical_svt`, `usb_ssic_physical_svt`,
`usb_agent_svt`, `usb_monitor_checker_svt`, `usb_protocol_svt`, `usb_subenv_svt` — i.e. the physical
package split mirrors the transactor-stack split (link/physical/protocol) plus agent/subenv/
monitor-checker wrapper packages, and a dedicated `usb_ssic_physical_svt` for SSIC.
Doc set version confirmed as **T-2022.09, September 2022** (title page of both UVM guide and GS
guide) — FAQ itself doesn't carry a version banner in the body but is packaged in the same release.
`dw_vip_setup -i home` prints installed library/model/example versions in one shot (FAQ §1.14).
