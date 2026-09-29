# USB VIP Examples — Deep Extraction (Category 3: VIP Examples)

Source root: `D:\DV\Task\USB\VIP\examples\` — 8 example programs. This report goes BEYOND
`tb_usb_svt_uvm_20_phy`'s env/connect_phase (already cited extensively in
`dv_harness/uvm_generator/generator.py`) and extracts real, distinct code patterns from all 8,
organized by the 10 target aspects: environment, configuration, interface, scoreboard, sequence,
sequence_item, test, constraint, coverage, callback.

Legend for which aspects each example actually demonstrates (✓ = real, substantive code found
and extracted below; the numbers are file counts observed in the `env/` directory listing):

| Example | env | cfg | if | scoreboard | sequence | seq_item | test | constraint | coverage | callback |
|---|---|---|---|---|---|---|---|---|---|---|
| tb_usb_svt_uvm_20_phy | ✓ | ✓ | ✓(UTMI/serial) | ✓ | ✓✓(60+ seqs) | ✓ | ✓ | ✓ | (VIP built-in only) | ✓✓(20+ cbs) |
| tb_usb_svt_uvm_20_b2b_phy | ✓ | ✓ | ✓(no DUT, phy-phy) | ✓ | ✓ | ✓ | ✓ | ✓ | (VIP built-in) | ✓ |
| tb_usb_svt_uvm_20_ulpi_phy | ✓ | ✓ | ✓(ULPI bridge) | ✓ | ✓✓(ULPI-specific) | ✓ | ✓ | ✓ | (VIP built-in) | ✓ |
| tb_usb_svt_uvm_basic_program_sys | ✓ | ✓ | ✓(program block, many DUT wrappers) | (via inline) | ✓✓(otg/ssic/isoc) | ✓ | ✓ | ✓ | (VIP built-in) | ✓✓ |
| tb_usb_svt_uvm_basic_router_sys | ✓✓(hub, multi-agent) | ✓✓(hub cfg) | ✓(hub if array) | ✓✓✓(3 SB types) | ✓✓(multi-tier hub) | ✓ | ✓ | ✓ | (VIP built-in) | ✓ |
| tb_usb_svt_uvm_basic_sys | ✓ | ✓ | ✓ | — | ✓✓(virtual seq collection) | ✓ | ✓ | ✓ | (VIP built-in) | ✓✓ |
| tb_usb_svt_uvm_cfg_validator | (minimal) | ✓✓✓(THE aspect) | — | — | — | — | ✓(cfg_validate) | — | — | — |
| tb_usb_svt_uvm_intermediate_sys | ✓✓(PIPE3/4) | ✓✓(LTSSM timers) | ✓(PIPE3/PIPE4) | ✓(uvm_in_order_comparator) | ✓(LTSSM) | ✓ | ✓ | ✓ | ✓✓✓(user covergroup) | ✓ |

---

## 1. tb_usb_svt_uvm_20_phy — the "kitchen sink" PHY-level example (baseline, already partly cited)

Path: `D:\DV\Task\USB\VIP\examples\tb_usb_svt_uvm_20_phy\`

This is the richest single example by file count (60+ sequence files, 20+ callback files) and is
the one the running USB build already cites for env/connect_phase. This section extracts what
was NOT already mined: the sequence_item/constraint base class, and the callback catalogue
(error-injection patterns), which are the real reusable patterns for a generation agent.

### 1a. sequence_item / constraint — `env/cust_svt_usb_transfer.sv`
This is **the** customization pattern used almost verbatim (with only weight-default changes)
across `tb_usb_svt_uvm_20_phy`, `tb_usb_svt_uvm_20_b2b_phy`, `tb_usb_svt_uvm_20_ulpi_phy`, and
(as `usb_svt_basic_cust_transfer`) `tb_usb_svt_uvm_cfg_validator`. It extends the VIP's
`svt_usb_transfer` sequence_item:

```systemverilog
class cust_svt_usb_transfer extends svt_usb_transfer;
  int CONTROL_IN_TRANSFER_wt = 1;   int CONTROL_OUT_TRANSFER_wt = 1;
  int BULK_OUT_TRANSFER_wt   = 1;   int BULK_IN_TRANSFER_wt     = 1;
  int ISOC_OUT_TRANSFER_wt   = 0;   int ISOC_IN_TRANSFER_wt     = 0;
  int INTR_OUT_TRANSFER_wt   = 1;   int INTR_IN_TRANSFER_wt     = 1;

  constraint xfer_type_distribution {
    xfer_type dist {
      svt_usb_transfer::CONTROL_TRANSFER := (CONTROL_IN_TRANSFER_wt + CONTROL_OUT_TRANSFER_wt),
      svt_usb_transfer::BULK_OUT_TRANSFER := BULK_OUT_TRANSFER_wt,
      svt_usb_transfer::BULK_IN_TRANSFER  := BULK_IN_TRANSFER_wt,
      svt_usb_transfer::ISOCHRONOUS_OUT_TRANSFER := ISOC_OUT_TRANSFER_wt,
      svt_usb_transfer::ISOCHRONOUS_IN_TRANSFER  := ISOC_IN_TRANSFER_wt,
      svt_usb_transfer::INTERRUPT_OUT_TRANSFER   := INTR_OUT_TRANSFER_wt,
      svt_usb_transfer::INTERRUPT_IN_TRANSFER    := INTR_IN_TRANSFER_wt
    };
  }
  constraint setup_data_bmrequesttype_dir_distribution {
    ((CONTROL_IN_TRANSFER_wt + CONTROL_OUT_TRANSFER_wt) > 0) -> {
      setup_data_bmrequesttype_dir dist {
        svt_usb_types::DEVICE_TO_HOST := CONTROL_IN_TRANSFER_wt,
        svt_usb_types::HOST_TO_DEVICE := CONTROL_OUT_TRANSFER_wt };
    }
  }
  // Payload-size caps to bound sim time, gated on xfer_type/direction:
  constraint payload_intended_byte_count_bulk_out {
    (xfer_type == svt_usb_transfer::BULK_OUT_TRANSFER) -> payload_intended_byte_count <= 1024;
  }
  constraint payload_intended_byte_count_control_out {
    ((xfer_type == svt_usb_transfer::CONTROL_TRANSFER) &&
     (setup_data_bmrequesttype_dir == svt_usb_types::HOST_TO_DEVICE)) ->
       payload_intended_byte_count <= 512;
  }
  constraint setup_data_w_length_control_in {
    ((xfer_type == svt_usb_transfer::CONTROL_TRANSFER) &&
     (setup_data_bmrequesttype_dir == svt_usb_types::DEVICE_TO_HOST)) ->
       setup_data_w_length <= 256;
  }
  `uvm_object_utils_begin(cust_svt_usb_transfer)
    `uvm_field_int(CONTROL_IN_TRANSFER_wt, UVM_ALL_ON|UVM_DEC)  // ... one per weight
  `uvm_object_utils_end
endclass
```
**Key pattern**: weight fields are plain `int`s exposed as UVM fields (settable via
`uvm_config_db`/factory or directly in a test's build_phase) that feed `dist` constraints — this
is the standard SVT idiom for "weighted transfer-type mix" and is reused by every sys-level
example (`cust_svt_usb_transfer.sv` appears in 7 of 8 examples with only the default weight
values differing). `tb_usb_svt_uvm_basic_sys`/`basic_program_sys` extend this ONE level further
with `cust_svt_isoc_transfer extends cust_svt_usb_transfer` (see §6b) adding ISOC-MULT weighted
`dist` on `endpoint_number`.

Constraint mechanics worth citing for a debug/generation agent: `usb_directed_transfers_sequence_multi_tier_hub.sv`
(router_sys, §5) shows the companion technique of **turning OFF** a built-in VIP constraint at
runtime: `usb_xfer[0].reasonable_control_transfer.constraint_mode(0);` before an inline
`randomize() with {...}` — used when a directed hub-class request (`w_value`, `w_index` set to
specific hub feature codes) would otherwise violate the VIP's own "reasonable" bounds.

### 1b. callback — error-injection catalogue (20+ files, all `svt_usb_*_callbacks` extensions)
All follow one of two base classes and hook one of a small set of extension points:
- `svt_usb_protocol_callbacks` — packet/transaction/transfer level hooks:
  `pre_usb_20_packet_out_port_put(component, chan_id, packet, transaction, packet_ix, transfer,
  transaction_ix, ref bit drop)`, `pre_transaction(component, transfer, transaction_ix)`,
  `randomized_transfer_complete_response(component, transfer)`.
- `svt_usb_physical_callbacks` — bit/symbol level hooks:
  `post_usb_20_link_data_in_port_get(component, chan_id, data, ref bit drop)`,
  `pre_usb_20_physical_data_out_port_put(component, chan_id, data, ref bit drop)`.

Concrete extracted examples:

**CRC16 error injection** (`env/svt_usb_crc16_error_callbacks_hs.sv`) — counts DATA packets as
they are about to leave the protocol layer and stamps the FIRST one with a CRC16 exception:
```systemverilog
class svt_usb_crc16_error_callbacks_hs extends svt_usb_protocol_callbacks;
  static int packet_count = 0;
  svt_usb_packet_exception packet_exc_temp;
  function void pre_usb_20_packet_out_port_put(svt_usb_protocol component, int chan_id,
      svt_usb_packet packet, svt_usb_transaction transaction, int packet_ix,
      svt_usb_transfer transfer, int transaction_ix, ref bit drop);
    if (( /* several xfer_type cases */ ) && (packet.pid_type == svt_usb_packet::DATA))
      packet_count++;
    if (packet_count == 1) begin
      packet_exc_temp.error_kind = svt_usb_packet_exception::CRC_ERROR;
      packet_exc_temp.crc_error  = svt_usb_packet_exception::CRC16_ERROR;
      packet.exception_list = new();
      packet.exception_list.add_exception(packet_exc_temp);
      packet_count++;
    end
  endfunction
endclass
```
Sibling files `svt_usb_crc16_error_callbacks_{fs,ls}.sv`, `svt_usb_protocol_crc5_error_callbacks*.sv`,
`svt_usb_protocol_invert_crc5_error_callbacks*.sv` follow the identical shape targeting
CRC5/token packets instead, per speed.

**Bit-stuff error injection** (`env/bit_stuff_error_callbacks.sv`) — THREE distinct classes in
one file, showing the two-sided (physical + protocol) technique:
- `usb_rx_error_data_error_callbacks extends svt_usb_physical_callbacks` — watches raw
  `svt_usb_data` bytes via `post_usb_20_link_data_in_port_get`, detects the DATA PID
  (`SVT_LOCAL_DATA_PID` macro checks for `8'hC3/4B/87/0F`), then on the next non-SOP/EOP byte
  forces `data.data = 8'hff` and attaches a `svt_usb_data_exception::BIT_STUFF_ERROR`.
- `usb_20_host_bitstuff_error_callbacks extends svt_usb_protocol_callbacks` — overrides
  `pre_transaction` to force the OUT payload to `USER_DEFINED_ALGORITHM` and fill it with
  `8'hFF` bytes (`transfer.payload.data = new[...]; ... UPDATE_PAYLOAD_BYTE(i,8'hFF)`) — the
  "worst case bit-stuff condition" pattern for maximizing 1-bits.
- `usb_20_dev_bitstuff_error_callbacks` — mirror of the above for the device's IN payload.

**Sync-field error injection** (`env/sync_phy_callbacks.sv`) — `svt_usb_physical_callbacks`,
hooks `pre_usb_20_physical_data_out_port_put`, and on the first SOP zeroes every
`*_ERROR_wt` field of a `svt_usb_data_exception` object except `SYNC_ERROR_wt = 1000`, then sets
`error_kind = SYNC_ERROR; sync_error = SHORT_SYNC_ERROR`. This "zero every weight except the one
you want, set it very high" idiom is the general SVT technique for forcing a specific error
subtype out of a weighted exception-kind enum.

Also present but not deep-read (same shape): `svt_usb_hs_no_eop_error_callback.sv`,
`svt_usb_hs_sync_with_j_error_callback.sv`, `svt_usb_fs_eop_error_callback.sv`,
`sync_prot_callbacks.sv`, `usb_20_get_status_packet_for_hnp_callback.sv` (HNP-specific
GET_STATUS packet field override), `host_fixed_inter_pkt_usb_20_diff_source_delay_callbacks.sv`
(inter-packet-delay override for HS handshake-source-delay tests),
`device_fixed_xfer_payload_callbacks.sv` / `in_xfers_payload_callbacks.sv` /
`in_xfers_setup_payload_callbacks.sv` / `in_out_xfers_payload_ipd_callbacks.sv` (payload/IPD
overrides), `usb_host_objection_management_callbacks.sv` /
`usb_device_objection_management_callbacks.sv` (the objection-raise/drop event pattern used by
every env's `objection_management` task — see §2 for the consuming side), `suspend_resume_callbacks.sv`.

### 1c. sequence catalogue (60+ files) — naming convention doubles as a scenario index
File names ARE the test intent (e.g. `attach_bulk_xfers_detach_fsls_serial_on_off_sequence.sv`,
`reset_during_non_suspend_hs_sequence.sv`, `lpm_l1_entry_remote_wakeup_sequence.sv`,
`vbus_off_during_data_transfer_sequence.sv`, `false_resume_on_suspend_hs_sequence.sv`,
`sync_illegal_error_detect_sequence.sv`). Each is `extends uvm_sequence` (or, for host-side mac
sequences, `uvm_sequence#(svt_usb_link_service)` / `#(svt_usb_protocol_service)`), follows the
UVM-version-guarded `pre_start`/`post_start` objection idiom shown below (identical body reused
in every example — this is THE canonical VIP sequence skeleton):

```systemverilog
`ifdef UVM_MAJOR_VERSION_1_0
  virtual task pre_body();  ... phase.raise_objection(this); ... endtask
  virtual task post_body(); ... phase.drop_objection(this);  ... endtask
`else
  virtual task pre_start();
    super.pre_start();
    if (get_parent_sequence() == null && phase!=null) phase.raise_objection(this);
  endtask
  virtual task post_start();
    if (get_parent_sequence() == null && phase!=null) phase.drop_objection(this);
  endtask
`endif
```
This dual-branch (only the top-level/root sequence in a nested call chain raises/drops the
phase objection — checked via `get_parent_sequence() == null`) is universal across ALL 8
examples' sequence files.

Two composite/collection files worth citing: `host_mac_sequence_collection.sv` and
`device_mac_sequence_collection.sv` register the whole test-selection set as
`default_sequence`-settable via `usb_20_phy_test_sequence_collection.sv`, which is itself the
thing `usb_20_phy_base_test.sv` points `uvm_config_db#(uvm_object_wrapper)::set(...,
"default_sequence", ...)` at per test file in `tests/ts.*.sv`.

### 1d. test — `env/usb_20_phy_base_test.sv` / `tests/ts.*.sv`
One base test per environment flavor; each `ts.<name>.sv` extends the base test and overrides
only the default-sequence config_db entry and sequence-specific knobs — e.g.
`ts.attach_bulk_xfers_detach_fs.sv` overrides to select
`attach_bulk_xfers_detach_fs_sequence`. (Same shape confirmed in the b2b and ulpi variants — see
below — and it matches the pattern already documented from the connect_phase citation.)

---

## 2. tb_usb_svt_uvm_20_b2b_phy — Host↔Device VIP wired directly, NO DUT

Path: `D:\DV\Task\USB\VIP\examples\tb_usb_svt_uvm_20_b2b_phy\`

### 2a. interface — the defining difference from `tb_usb_svt_uvm_20_phy`
`top.sv` is IDENTICAL boilerplate to `tb_usb_svt_uvm_20_phy/top.sv` (`` `include "top_test.sv" ``
after optional custom timescale) — the actual difference is entirely in `top_test.sv`, where
**two `nvs_usb_phy` PHY model instances are wired to each other's DP/DM** through a single shared
`wor DP, DM` pair, with NO third "DUT" instance at all:
```systemverilog
wor DP,DM;
...
nvs_usb_phy SNPS_HOST_PHY_INST ( ... .DP(DP), .DM(DM), ... .usb_clk_out(utmi_clock_from_host_phy), ... );
nvs_usb_phy SNPS_DEV_PHY_INST  ( ... .DP(DP), .DM(DM), ... .usb_clk_out(utmi_clock_from_dev_phy),  ... );
```
Both PHY models are driven by the SAME `usb_20_serial_if.usb_20_serial_if.clk1x_480Mhz` clock
source generated in `top_test.sv` itself (an 8-phase manually-toggled clock generator producing
the nominal 2083ps UTMI cycle, `usb_20_simulation_cycle = 2083`). This is the reference pattern
for "loopback"/"back-to-back" VIP-to-VIP testbenches with no RTL DUT: each side gets its own
UTMI `svt_usb_if` (`usb_20_utmi_host_if`, `usb_20_utmi_dev_if`) registered to
`uvm_test_top.env` via `uvm_config_db#(virtual svt_usb_if)::set(...)`, plus a third
`usb_20_serial_if` used purely for the differential bus monitor / serial clock source.
`SVT_USB_USE_EXTERN_CLK_TB` also guards an alternate testbench-generated-clock mode with its own
5GHz/500MHz/serial/jitter clock set (unused by default here).

### 2b. environment / configuration / test — same shape as 20_phy, reduced sequence set
`env/usb_20_phy_env.sv`, `env/usb_shared_cfg.sv`, `env/usb_20_phy_base_test.sv` mirror the
20_phy versions verbatim (same host_agent/dev_agent/sys_virt_sequencer construction, same
`objection_management` fork/join_none pattern). The env file inventory is a strict SUBSET of
20_phy's — this example intentionally trims to ~20 sequence files (`attach_bulk_xfers_detach_fs/hs`,
`eop_detect_*`, `rx_random_xfers`, `suspend_*`, `host_resume`) because it exists to validate
host↔device VIP protocol conformance in isolation, not DUT integration scenarios (no `lpm_*`,
no `ulpi_*`, no `vbus_off_*`, no CRC/bitstuff error-injection sequences — those require a real
PHY/DUT boundary to inject errors on).

### 2c. what's genuinely new here vs. 20_phy
`env/usb_data_scoreboard.sv`, `usb_packet_scoreboard.sv`, `usb_transaction_scoreboard.sv`,
`usb_transfer_scoreboard.sv` are present (same 4-scoreboard set as 20_phy — not new), but
`in_xfers_payload_callbacks.sv` / `in_transfer_sequence_callbacks.sv` /
`suspend_resume_callbacks.sv` / `svt_usb_fs_eop_error_callback.sv` /
`usb_device_response_payload_callbacks.sv` are the ONLY callback files retained — confirming
that back-to-back testing needs response-shaping callbacks (device must supply IN data since
there's no real DUT function) but not physical-layer error-injection callbacks.

---

## 3. tb_usb_svt_uvm_20_ulpi_phy — ULPI 8-bit link interface, PHY-side bridging

Path: `D:\DV\Task\USB\VIP\examples\tb_usb_svt_uvm_20_ulpi_phy\`

### 3a. interface — `env/usb_ulpi_dut_sv_wrapper.sv`: the ULPI↔UTMI bridge pattern
This is the standout interface artifact of the whole example set. It wires THREE things
together in one module: (1) a `svt_usb_phy_ulpi` VIP-provided ULPI PHY BFM instance
(`usb_20_ulpi_if` port bound to `usb_dut_mac_if`, i.e. the VIP drives the ULPI 8-bit bus
directly as if it were a PHY talking to a MAC/link-layer DUT), (2) an `nvs_usb_phy` UTMI-level
PHY model instance bridging ULPI's `FSVPLUS/FSVMINUS/FSLSRCV` (analog FS/LS signals) out to a
serial `DP/DM` pair via `tran` primitives, and (3) an intermediate `svt_usb_if
usb_20_phy_dut_intermediate_if` used only to carry UTMI-shaped signals between the two model
instances (never exposed to the outer testbench). Representative port bindings:
```systemverilog
svt_usb_phy_ulpi phy_ulpi (
  .usb_20_ulpi_if (usb_dut_mac_if),
  .ULPISTP(test_top.stp), .ULPIDATAIN(test_top.datain),
  .PHYCLOCK(clk_phy_ulpi), .DATAOUT(DataOut), .TXREADY(TXReady),
  .RXACTIVE(RXActive), .RXVALID(RXValid), .RXERROR(RXError), .LINESTATE(LineState),
  .ULPIDATAOUT(test_top.dataout), .ULPICLOCK(test_top.clk),
  .ULPIDIR(test_top.dir), .ULPINXT(test_top.nxt),
  .DATAIN(usb_20_phy_dut_intermediate_if.utmi_dut_mac_if.DataIn[7:0]),
  .TXVALID(...TXValid), .SUSPENDM(...SuspendM), .XCVRSEL(...XcvrSelect),
  .TERMSEL(...TermSelect), .OPMODE(...OpMode), .TXBITSTUFFEN(...TxBitstuffEnable),
  .DPPULLDOWN(dp_pulldown), .DMPULLDOWN(dm_pulldown), .DRVVBUS(...DrvVbus), ...
);
nvs_usb_phy SNPS_PHY_INST ( .usb_clk_in(...), .usb_reset(top_rst_phy),
  .usb_databus16_8(...DataBus16_8), ..., .Vbus(usb_dut_serial_if.usb_20_serial_if.vbus), ... );
tran dp_xmit(test_top.DP, usb_dut_serial_if.usb_20_serial_if.dp);
tran dm_xmit(test_top.DM, usb_dut_serial_if.usb_20_serial_if.dm);
```
**Cross-reference / contradiction note**: this proves the "PHY interface" family in this VIP
covers at least three distinct physical realizations exercised across the examples —
UTMI-serial (20_phy/b2b_phy top_test.sv), ULPI (this wrapper), and PIPE3/PIPE4 (intermediate_sys,
§8) — each requiring a DIFFERENT sv_wrapper/bridging module. A generation agent must not assume
"the interface" is UTMI by default; it must check `usb_20_signal_interface` /
`usb_ss_signal_interface` enum values (`UTMI_IF`, `ULPI_IF`, `USB_20_SERIAL_IF`,
`USB_20_TLM`, `PIPE3_IF`, `PIPE4_IF`, `USB_SS_SERIAL_IF`, `USB_SS_TLM`) in the configuration to
know which wrapper/topology applies.

### 3b. sequence — ULPI-protocol-specific sequences (unique to this example, ~25 files)
Distinct sequence family not present anywhere else: `ulpi_reg_rd_wr_sequence.sv`,
`ulpi_immediate_reg_rd_usb_receive_sequence.sv`, `ulpi_immediate_reg_wr_rd_link_abort_sequence.sv`,
`ulpi_immediate_reg_set_clr_sequence.sv`, `ulpi_extended_reg_rd_wr_sequence.sv`,
`ulpi_ext_reg_{rd,wr}_followed_by_usb_receive_sequence.sv`,
`ulpi_usb_receive_interrupted_by_ext_reg_{rd,wr}_sequence.sv`,
`ulpi_usb_receive_interrupted_followed_by_no_txcmd_sequence.sv`,
`ulpi_usb_receive_aborted_in_same_cycle_as_dir_assertion_sequence.sv`,
`ulpi_txabort_during_tx_packet_transmission_sequence.sv`,
`ulpi_reg_{rd,wr}_interruption_by_rxcmd_and_rx_sequence.sv`,
`ulpi_function_control_opmode_{00,01,10,11}_sequence.sv`,
`ulpi_function_control_xcvrselect_termselect_sequence.sv`,
`ulpi_function_control_disable_ls_{fs,on_fs}_sequence.sv`,
`ulpi_function_control_reset_{,hs_to_fs_}sequence.sv`,
`ulpi_vendor_product_id_rd_sequence.sv`. These target ULPI-specific link-layer service items
(register access via the ULPI 8-bit bus, DIR/NXT/STP handshake races with in-flight USB
receive/transmit) that have no UTMI or PIPE equivalent — i.e. ULPI register access is a
protocol-service concern orthogonal to `svt_usb_transfer`.

### 3c. everything else — identical shape to 20_phy
`env/usb_20_phy_env.sv`, `usb_shared_cfg.sv`, `usb_20_phy_base_test.sv`,
`usb_20_phy_test_sequence_collection.sv`, and all 4 scoreboards and all CRC/bitstuff/sync
callback files are present unchanged from 20_phy — ULPI is a drop-in interface-layer swap under
the same env/cfg/test scaffolding, not a different environment architecture.

---

## 4. tb_usb_svt_uvm_basic_program_sys — many DUT topologies, `program` block, OTG/SSIC richness

Path: `D:\DV\Task\USB\VIP\examples\tb_usb_svt_uvm_basic_program_sys\`

### 4a. interface — 10 `top.<variant>.sv` files, each a full alternate topology
`top.usb_20_eusb2{,_device_repeater,_host_repeater}.sv`, `top.usb_20_eusb2v2.sv`,
`top.usb_20_hsic.sv`, `top.usb_20_serial.sv`, `top.usb_20_ulpi_{device,host}.sv`,
`top.usb_20_utmi.sv`, `top.usb_ss_pipe3.sv`, `top.usb_ss_serial.sv`. `prescript` (a Makefile-run
csh script, shared mechanism across every `sys` example) copies the ONE matching `top.<variant>.sv`
to `test_top.sv` based on which scenario/test is invoked — i.e. **the DUT topology is selected
at build/prescript time, not at UVM run time**. Matching `hdl_interconnect/` wrapper Verilog
files exist for each DUT flavor: `usb_20_eusb2_dut{,_sv_wrapper}`, `usb_20_hsic_dut{,_sv_wrapper}`,
`usb_20_serial_dut{,_sv_wrapper}`, `usb_20_utmi_dut_sv_wrapper`, `usb_ss_pipe3_dut{,_sv_wrapper}`,
`usb_ss_serial_dut{,_sv_wrapper}`, `usb_ssic_serial_dut{,_sv_wrapper}`, `utmi_dut.v`. This
confirms: for a DUT-integration environment (vs. the phy-only examples above), the DUT
model/wrapper choice is compiled in per test, and the `env` classes stay DUT-topology-agnostic
by only knowing about `svt_usb_if` handles bound via `uvm_config_db`.

### 4b. sequence/callback — OTG and SSIC-specific material unique to this + basic_sys
`usb_20_otg_sequence.sv`, `usb_ss_otg_rsp_with_warm_rst_aft_curr_xfer_virt_sequence.sv` +
paired `usb_ss_otg_rsp_with_warm_rst_aft_curr_xfer_testcase_protocol_callbacks.sv` (OTG
role-swap + warm-reset-after-pending-transfer scenario, a virtual-sequence + matched-callback
pair — the callback likely intercepts the protocol-service response to trigger the warm reset
at the right point). `usb_ssic_*` sequence family (7 files:
`concurrent_u1_u2`, `dsp_disconnect_reconnect`, `hot_reset`, `inactivity_u1_u2_entry`,
`lgo_ux_response`, `mphy_test_mode_tx_compliance_mode`, `no_wait_u2_entry_exit`,
`rrap_disable_lup_ldn`) each has a matching `_virtual_sequence.sv` wrapper plus a shared
`usb_ssic_startup_sequence.sv`/`usb_ssic_startup_virtual_sequence.sv` bring-up sequence — these
are SSIC (SuperSpeed Inter-Chip) LTSSM/link-power-state scenarios layered as virtual sequences
over the base env's `sys_virt_sequencer`.

### 4c. test — `usb_base_test.sv` (identical structure to every other example's base test:
`cfg.setup_usb_ss_defaults()`; register cfg via `uvm_config_db`; set
`env.host_agent.xfer_sequencer.main_phase` default_sequence to `usb_random_transfer_sequence`;
`set_inst_override_by_type(..., svt_usb_transfer::get_type(), cust_svt_usb_transfer::get_type())`;
create env; standard `final_phase` pass/fail epilogue from `uvm_report_server` severity counts).
Also has `usb_inline_base_test.sv` + `usb_basic_inline_env.sv` — an "inline" env variant
(distinct from `usb_basic_serial_env.sv`) with its own objection-management callback pair
(`usb_inline_env_{host,device}_objection_management_callbacks.sv`), suggesting an env
architecture where agents are instantiated directly under the test rather than through a
dedicated env class layer — worth flagging as an alternate/lighter-weight env pattern.

---

## 5. tb_usb_svt_uvm_basic_router_sys — Hub/multi-tier topology; the richest scoreboard + env example

Path: `D:\DV\Task\USB\VIP\examples\tb_usb_svt_uvm_basic_router_sys\`

This is the deepest environment and the ONLY example with 3 independent, fully worked
scoreboard levels (transfer/transaction/packet) wired simultaneously, plus a multi-agent,
multi-array (parameterized `` `SVT_USB_NUM_HUB_INST ``, `` `SVT_USB_NUM_DEVICE_INST ``,
`` `SVT_USB_NUM_OF_DOWNSTREAM_PORTS_INST ``) environment.

### 5a. environment — `env/usb_hub_basic_env.sv`
Structural facts a generation agent needs:
- Agent arrays, not singletons: `svt_usb_hub_agent hub_agent[`SVT_USB_NUM_HUB_INST]`;
  `svt_usb_agent dev_agent[`SVT_USB_NUM_DEVICE_INST]`; each device also gets an optional
  passive `dev_mon_agent[i]` (`is_active=0`) gated by `cfg.enable_dev_mon[i]`.
- Per-instance interface registration uses `$psprintf` to build the config_db instance-name
  string, e.g. `` string_dev_cfg = $psprintf("dev_agent[%0d]",i); uvm_config_db#(...)::set(this, string_dev_cfg, "cfg", cfg.dev_cfg[i]); `` — this indexed-string-path idiom is the general
  pattern for configuring N-way agent arrays via `uvm_config_db`.
- **remote_cfg cloning chain for hub topologies**: for EVERY link boundary that uses PIPE3/PIPE4/
  UTMI (i.e. a MAC-side connection needing to know the peer's config), the env clones the
  peer's config object (`$cast(remote_cfg, this.cfg.hub_cfg[i].upstream_cfg.clone())`), forces
  `remote_cfg.component_subtype = svt_usb_configuration::PHY`, validates it
  (`remote_cfg.is_valid(0)`), then registers it under the OTHER side's agent path
  (`"downstream_remote_cfg[j]"`, `"upstream_remote_cfg"`, `"remote_cfg"` depending on link). This
  clone-and-relabel-as-PHY pattern repeats ~6 times in this env for host→hub-upstream,
  hub-downstream→next-hub-upstream, and last-hub-downstream→device links — it is the general
  mechanism for wiring MAC/PHY split VIP topologies at ANY tier depth.
- **Callback attach point differs from the simple envs**: uses `end_of_elaboration_phase` (not
  `build_phase`) to attach a link-layer packet-delay callback:
  ```systemverilog
  function void usb_hub_basic_env::end_of_elaboration_phase(uvm_phase phase);
    super.end_of_elaboration_phase(phase);
    pkts_cb = new();
    uvm_callbacks#(svt_usb_link)::add(this.hub_agent[0].downstream_agent[0].link, pkts_cb);
  endfunction
  ```
  with `pkt_callback extends svt_usb_link_callbacks` overriding
  `pre_usb_ss_tx_packet_transform(component, packet, ref bit drop)` to set
  `packet.inter_pkt_delay = 100ns;` — a LINK-layer callback class distinct from the
  protocol/physical callback classes seen elsewhere (three different callback base classes now
  confirmed: `svt_usb_protocol_callbacks`, `svt_usb_physical_callbacks`,
  `svt_usb_link_callbacks`).
- **connect_phase wiring for 3 scoreboards simultaneously** (conditional on cfg flags):
  ```systemverilog
  if(cfg.enable_transfer_scoreboard==1) begin
    dev_transfer_observed_port.connect(xfer_sb.dev_xfer_ended_axp);
    host_transfer_observed_port.connect(xfer_sb.host_xfer_ended_axp);
  end
  if(cfg.enable_transaction_scoreboard==1) begin
    dev_transaction_observed_port.connect(xact_sb.dev_xact_ended_axp);
    host_transaction_observed_port.connect(xact_sb.host_xact_ended_axp);
  end
  if(cfg.enable_packet_scoreboard==1) begin
    dev_usb_ss_packet_tx_observed_port.connect(pkt_sb.dev_ss_pkt_tx_ended_axp);
    host_usb_ss_packet_tx_observed_port.connect(pkt_sb.host_ss_pkt_tx_ended_axp);
    dev_usb_ss_packet_rx_observed_port.connect(pkt_sb.dev_ss_pkt_rx_ended_axp);
    ... (8 total connects: ss/20 x tx/rx x host/dev)
  end
  ```
  Note the env does NOT get transfers/transactions/packets from a VIP analysis port directly —
  it polls `uvm_event`s from the agent's internal event pool (`NOTIFY_USB_TRANSFER_ENDED`,
  `NOTIFY_USB_TRANSACTION_ENDED`, link's `NOTIFY_TX_PACKET_ENDED`/`NOTIFY_RX_PACKET_ENDED`) inside
  a `run_phase` fork (`supply_analysis_ports()` task, with one `wait_for_dev_*_ended(inst)` task
  spawned per device instance) and re-publishes onto its OWN analysis ports which the
  scoreboards subscribe to. **This is a materially different scoreboard-feed architecture** from
  `usb_intermediate_pipe4_env.sv` (§8) which connects the scoreboard DIRECTLY to
  `host_agent.prot.transfer_observed_port` — a generation agent should know both patterns exist
  and pick based on whether transaction/packet-level (not just transfer-level) comparison is
  needed.

### 5b. scoreboard — 3 distinct implementations, 2 different comparison strategies

**`usb_transaction_scoreboard.sv` and `usb_transfer_scoreboard.sv`** (transfer_scoreboard not
fully quoted above but shares transaction_scoreboard's shape): analysis-imp based
(`` `uvm_analysis_imp_decl(_dev_xact_ended) ``, `` `uvm_analysis_imp_decl(_host_xact_ended) ``),
each side pushes into its own queue (`dev_xact_ended_queue[$]`, `host_xact_ended_queue[$]`) plus
triggers an `event`; a single `post_xact_sb_compare()` task runs a `forever` loop that pops the
next host item and does a linear `foreach` search in the device queue for a match on
`(device_address, endpoint_number, xact_type)`, blocking on the `new_dev_xact_received` event if
no match found yet, then compares with `uvm_comparer` configured
`.physical=1; .abstract=0` (i.e. the "RELEVANT" compare policy) via `host_xact.do_compare(dev_xact, relevant_comp_policy)`.
Address filtering: `write_host_xact_ended` cross-checks the incoming transaction's
`device_address` against `device_cfg[]` (set via `set_device_cfg()`) before accepting it — this
filters out transactions targeting OTHER devices/hubs on a shared bus. Reports
`sb_matches`/`sb_mismatches` in `report_phase`, `uvm_error("Scoreboard Report","Comparison FAILED")`
on mismatch, and a non-fatal `uvm_warning` if either queue is non-empty at the end (residual
un-matched transactions).

**`usb_packet_scoreboard.sv`** — same queue/event architecture but SPLIT 4 ways (SS-tx, 20-tx,
SS-rx, 20-rx) × (host, device) = 8 analysis imps and 8 queues, plus a `pkt_addr_q[$]` address
filter built from `set_device_cfg()`. Comparison logic in `post_pkt_sb_compare()` runs 4
concurrent `fork...join` blocks (host-ss-tx↔dev-ss-rx, dev-ss-tx↔host-ss-rx, host-20-tx↔dev-20-rx,
dev-20-tx↔host-20-rx), each internally doing an endpoint-number match search
(`host_pkt.ept_num==dev_pkt.ept_num`) with a `TRANSACTION_PACKET`/`DATA_PACKET`-vs-other-type
branch (non-transaction/data packets like handshakes are matched FIFO-order instead of by
endpoint, via straight `pop_front()`), then `do_sb_compare()` using a CUSTOM
`extend_uvm_comparer extends svt_comparer` with `get_kind()` returning
`` `SVT_DATA_TYPE::RELEVANT `` — a THIRD distinct compare-policy mechanism (vs.
`uvm_comparer.physical/abstract` in transaction_scoreboard, vs. `usb_transfer_comp` static
`comp()` wrapper class in `usb_uvm_scoreboard.sv`, §8). LINK_MANAGEMENT_PACKETs are explicitly
excluded from comparison (`pkt_l.pkt_type != svt_usb_packet::LINK_MANAGEMENT_PACKET`). Also
exposes `flush_scoreboard()` (clears all 8 queues + counters) for use "externally from env in
case of Vbus getting off in between of simulation" — i.e. a hook for handling detach/reset mid-test.

### 5c. configuration — `env/usb_hub_shared_cfg.sv`
Extends the host/device pattern (seen in §7's `usb_svt_shared_cfg`) with a THIRD config array:
`svt_usb_hub_agent_configuration hub_cfg[]` (sized `` `SVT_USB_NUM_HUB_INST `` in the
constructor), each hub_cfg element itself containing `upstream_cfg` (the hub's own device-side
config, talking to the host/parent hub) and `downstream_cfg[]` (array sized
`` `SVT_USB_NUM_OF_DOWNSTREAM_PORTS_INST ``, one HOST-role config per downstream port). The
constructor wires the full chain of `remote_device_cfg`/`remote_host_cfg` cross-links: host's
`remote_device_cfg[0..N-1]` point at hub_cfg upstream local_device_cfg[0]'s (so host "sees" each
hub as a device), and each `hub_cfg[i].downstream_cfg[j].remote_device_cfg[0]` points at
`dev_cfg[j].local_device_cfg[0]` (so each hub downstream port "sees" its attached device) —
`host_cfg.remote_device_cfg_size = `SVT_USB_NUM_DEVICE_INST + `SVT_USB_NUM_HUB_INST` sizes the
combined visibility array. `setup_usb_ssp_defaults()` configures ESSG2 (Enhanced SuperSpeed
Gen2) speed end-to-end (`host_cfg.speed = svt_usb_types::ESSG2`,
`usb_ess_speed_max/min = ESSG2`) — confirming the VIP models ESS (USB 3.2) Gen1x1/Gen1x2/Gen2x1
via this `usb_ess_speed_{max,min}` pair distinct from the plain `speed` field, and that hub
upstream ports get exactly 2 endpoints (CONTROL ep0, INTERRUPT-IN ep1 status-change pipe, with
`` `ifdef SVT_USB_HUB_POLLING_ENABLE `` gating `disable_ss_host_polling=1'b1` on that INTERRUPT
endpoint — i.e. polling-vs-ERDY-based hub status notification is a compile-time choice).
Also carries `bit concurrent_test` (shifts `start_index_remote_device_cfg` by
`` `SVT_USB_NUM_HUB_INST*2 `` when set — used for tests running two hub trees concurrently) and
enable flags for each scoreboard type (`enable_transfer_scoreboard`,
`enable_transaction_scoreboard` default 1, `enable_packet_scoreboard` default 0) plus
`enable_host_mon`/`enable_dev_mon[]` for optional passive monitor agents.

### 5d. sequence — `usb_directed_transfers_sequence_multi_tier_hub.sv` (full USB hub enumeration
by hand, in-band via control transfers)
This is the single most instructive REAL sequence in the entire example set for understanding
manual USB enumeration over a hub tree. Key sub-tasks, each built from raw
`svt_usb_transfer` randomize-with-inline-constraints against SETUP-packet fields:
- `hub_set_depth(hub_depth, cfg)`: sends `HUB_CLASS_SET_HUB_DEPTH` (a CLASS/DEVICE-recipient
  request) with `setup_data_w_value == hub_depth` — required per-USB3 spec for multi-tier hubs
  to know their own depth.
- `hub_set_addr_set_config(dev_index, address, cfg)`: two back-to-back control transfers,
  `SET_ADDRESS` (`setup_data_brequest == svt_usb_types::SET_ADDRESS; setup_data_w_value ==
  address`) then `SET_CONFIGURATION` (`w_value[7:0]==8'd1`), each followed by
  `xfer.end_event.wait_on()` before proceeding — the canonical two-step device-bring-up
  sequence. Comment clarifies: *"Since Device VIP does not interpret control transfers, this
  SET_ADDRESS does not change Device VIP's device address"* — i.e. these directed control
  transfers exercise host-side protocol correctness but the device VIP's actual `device_address`
  field is set separately via config (`cfg.remote_device_cfg[i].connected_hub_device_address = ...`).
- `enumerate_downstream_device(port, cfg, downstream_hub, tier)`: `HUB_CLASS_SET_FEATURE` with
  `w_value==8` (PORT_POWER) then, for 2.0 speeds, `w_value==4` (PORT_RESET), each gated by
  `` `ifdef SVT_USB_HUB_POLLING_ENABLE `` around an optional `polling_port()` call; waits on
  `env.hub_agent[tier-1].downstream_agent[port-1].shared_status.link_usb_20_state ==
  svt_usb_types::{DEVICE_ATTACHED,ENABLED}` or, for SS, `.shared_status.ltssm_state == U0` on
  BOTH the hub's downstream port and the actual device/next-hub-upstream agent concurrently
  (`fork ... join`).
- `polling_port()`: full interrupt-endpoint hub status-change poll loop — sends a 4-byte IN
  transfer to the hub's status-change endpoint, waits on
  `env.host_agent.prot.NOTIFY_USB_TRANSFER_ENDED.wait_trigger_data(...)`, checks
  `usb_xfer[1].status == `SVT_TRANSACTION_TYPE::ABORTED` (meaning NAK'd / nothing to report) vs.
  a real change-bitmap payload, then issues `HUB_CLASS_GET_STATUS` (`w_index==port`) to decode
  `wPortChange`/`wPortStatus` 16-bit fields from the 4-byte response
  (`{data[3],data[2]}`/`{data[1],data[0]}`), branches on bit 0 (connect), bit 4 (reset
  complete), bit 2 (resume complete) to pick the right `HUB_CLASS_CLEAR_FEATURE` value (16/19/18
  respectively), then issues that clear.
- Top-level `body()` scales all of this across up to 5 hub tiers via literal `if
  (SVT_USB_NUM_OF_HUB_INST_PARAM > N)` cascades (not a generic loop) — worth noting as a
  limitation/hard cap in the reference sequence if a generation agent needs >5 tiers.

Related, not deep-read but confirmed present: `usb_port_suspend_resume_sequence{,_multi_tier_hub}.sv`,
`usb_port_link_state_sequence_multi_tier_hub.sv`, `usb_directed_concurrent_transfers_sequence.sv`,
`usb_directed_transfers_sequence_multi_tier_hub.sv`'s simpler sibling
`usb_directed_transfers_sequence.sv` (single-tier version), `usb_fsls_service_sequence.sv`.

---

## 6. tb_usb_svt_uvm_basic_sys — non-program sys variant; virtual sequence collection; broadest callback set

Path: `D:\DV\Task\USB\VIP\examples\tb_usb_svt_uvm_basic_sys\`

Near-identical file inventory to `basic_program_sys` (both share nearly the same `env/` file
list) — the real difference is `top.sv`/`top.<variant>.sv` use a plain `module` testbench (not
a SystemVerilog `program` block), and this example adds
`usb_transfer_system_virtual_sequence_collection.sv` (absent from basic_program_sys).

### 6a. sequence — `usb_bulk_random_endpoint_stream_system_virtual_sequence` (virtual sequence
spanning BOTH host and device virtual sequencers, with explicit uStream IDs)
Declared `` `uvm_declare_p_sequencer(svt_usb_system_virtual_sequencer) `` (the SYSTEM-level
sequencer, not a single agent's), it looks up BOTH agents via
`p_sequencer.host_virt_sequencer.find_first_agent(this)` /
`p_sequencer.dev_virt_sequencer.find_first_agent(this)`, waits for both sides'
`shared_status.ltssm_state == U0`, then for each of `svt_usb_no_of_bulk_{out,in}_stream_xfers`
transfers:
1. Randomizes an `svt_usb_transfer` with explicit `ustream_id == (i+1)` (SuperSpeed bulk
   streams — USB attribute for out-of-order bulk endpoint pipes),
2. Issues a `USB_TRANSFER_AVAILABLE` **protocol_service** command on the DEVICE's
   `prot_service_sequencer` FIRST (`prot_srvc.direction = OUT/IN; prot_srvc.ustream_id =
   usb_xfer.ustream_id; p_sequencer.dev_virt_sequencer.prot_service_sequencer.execute_item(...)`)
   — i.e. the device side must be told "buffer is ready for this stream" BEFORE the host's
   transfer is sent,
3. Publishes the payload size to a wildcard config_db path
   (`uvm_config_db#(int unsigned)::set(null, "*", "svt_usb_bulk_out_payload_size", ...)`) —
   presumably consumed by a payload-callback elsewhere,
4. THEN executes the transfer directly on `host_agent.xfer_sequencer.execute_item(usb_xfer)`
   (note: `execute_item`, not `` `uvm_send `` — a lower-level direct-execute call bypassing the
   normal `uvm_do`/response-queue machinery) and blocks on `usb_xfer.end_event.wait_on()`.
This is the reference pattern for bulk-stream (USB 3.x `ustream_id`) sequencing requiring
explicit device-buffer-ready coordination via the protocol_service channel — materially
different from every other sequence in the set, which just calls `` `uvm_send `` on the
xfer_sequencer.

### 6b. sequence_item / constraint — `cust_svt_isoc_transfer.sv` (extends `cust_svt_usb_transfer`)
```systemverilog
class cust_svt_isoc_transfer extends cust_svt_usb_transfer;
  int ISOC_IN_MULT_ONE_TRANSFER_wt = 4;  int ISOC_IN_MULT_TWO_TRANSFER_wt = 4;
  int ISOC_IN_WITHOUT_MULT_TRANSFER_wt = 4; // + OUT-side mirrors
  constraint payload_intended_byte_count_isoc_out {
    (xfer_type == svt_usb_transfer::ISOCHRONOUS_OUT_TRANSFER) -> payload_intended_byte_count <= 1024;
  }
  constraint isoc_mult_distribution {
    if (xfer_type == ISOCHRONOUS_IN_TRANSFER) {
      endpoint_number dist { 2 := ISOC_IN_WITHOUT_MULT_TRANSFER_wt,
                              4 := ISOC_IN_MULT_TWO_TRANSFER_wt,
                              5 := ISOC_IN_MULT_ONE_TRANSFER_wt };
    }
    if (xfer_type == ISOCHRONOUS_OUT_TRANSFER) { /* mirror on OUT endpoints */ }
  }
  function new(...);
    super.new(name);
    CONTROL_IN_TRANSFER_wt = 1; ISOC_IN_TRANSFER_wt = 4; ISOC_OUT_TRANSFER_wt = 4;
    ISOC_DATA_TRANSFER_wt = 100; ISOC_PING_TRANSFER_wt = 0;  // suppress ISOC PING
  endfunction
endclass
```
This demonstrates the pattern of picking a SPECIFIC endpoint NUMBER (2 vs 4 vs 5) to route
generated traffic to endpoints pre-configured (elsewhere, via `endpoint_cfg[].isoc_mult` /
`.mult`) for "no MULT", "MULT=1", "MULT=2" isochronous burst variants — i.e. constraining
`endpoint_number` is how a sys-level sequence_item targets specific pre-configured endpoint
behaviors rather than randomizing endpoint selection freely. Also demonstrates SUBCLASS-ADDS-A-
DIST-ON-A-FIELD-THE-PARENT-ALREADY-CONSTRAINS pattern (base class distributes `xfer_type`; this
subclass further distributes `endpoint_number` conditionally on `xfer_type`).

### 6c. callback — `device_expected_payload_callbacks.sv` / `host_expected_payload_callbacks.sv`
(paired host+device callback classes implementing an ISOC OUT/IN payload hand-off queue between
independently-generated host and device sequences):
```systemverilog
class host_expected_payload_callbacks extends svt_usb_protocol_callbacks;
  usb_ssic_rmmi_env env;
  virtual function void post_transfer_in_port_get(svt_usb_protocol component, int chan_id,
      svt_usb_transfer transfer, ref bit drop);
    if (transfer.xfer_type == ISOCHRONOUS_OUT_TRANSFER) env.iso_out_xfer_q.push_back(transfer);
    if (transfer.xfer_type == ISOCHRONOUS_IN_TRANSFER)  env.iso_in_xfer_q.push_back(transfer);
  endfunction
endclass

class device_expected_payload_callbacks extends svt_usb_protocol_callbacks;
  usb_ssic_rmmi_env env;
  virtual function void pre_transfer_out_port_put(svt_usb_protocol component, int chan_id,
      ref svt_usb_transfer transfer, ref bit drop);
    `SVT_XVM(object) xfer=null; svt_usb_transfer host_xfer;
    if (transfer.xfer_type==ISOCHRONOUS_OUT_TRANSFER) xfer = env.iso_out_xfer_q.pop_front();
    if (transfer.xfer_type==ISOCHRONOUS_IN_TRANSFER)  xfer = env.iso_in_xfer_q.pop_front();
    if (xfer != null && $cast(host_xfer, xfer)) begin
      transfer.payload_intended_byte_count = host_xfer.payload_intended_byte_count;
      transfer.aligned_transfer_ends_with_zero_length = host_xfer.aligned_transfer_ends_with_zero_length;
      transfer.first_isoc_transaction = host_xfer.first_isoc_transaction;
      transfer.last_isoc_transaction  = host_xfer.last_isoc_transaction;
    end
  endfunction
endclass
```
Pattern: the HOST side's callback taps `post_transfer_in_port_get` (fired after the host's own
randomized transfer object is available) to STASH a copy in an env-level queue; the DEVICE
side's callback taps `pre_transfer_out_port_put` (fired before the device issues its own
independently-generated transfer for the SAME isoc endpoint) to POP that stashed host transfer
and COPY specific fields (byte count, alignment, first/last-isoc-transaction markers) across —
this is how two independently-randomizing agents stay isochronous-transfer-size-consistent
without a shared sequence. `ref svt_usb_transfer transfer` (by-ref, mutable) on the device side
vs. plain `svt_usb_transfer transfer` (read-only inspect) on the host side reflects the
producer/consumer roles precisely.

### 6d. callback — `base_test_error_and_warning_catcher.sv` (message severity-demotion pattern)
`extends svt_err_catcher`, holds 5 separate message-pattern queues
(`warning_msg[$]`, `error_msg[$]`, `error_warning_msg[$]`, `fatal_msg[$]`, `info_msg[$]`) each
checked via a hand-rolled `pattern_match(str1, str2)` substring search (O(n) sliding-window
`substr` compare — no regex), and a `catch()` override that demotes matched
WARNING/ERROR/FATAL messages to `UVM_INFO` and returns `THROW` (i.e. it demotes severity but
does NOT suppress the message from being printed) — except matched INFO messages, which return
`CAUGHT` (fully suppressed). This is the standard "expected error/warning demotion" idiom for
directed negative tests where a specific VIP-emitted error is the intended, checked outcome
rather than a real failure.

---

## 7. tb_usb_svt_uvm_cfg_validator — the ONE example that IS the configuration aspect

Path: `D:\DV\Task\USB\VIP\examples\tb_usb_svt_uvm_cfg_validator\`

Smallest example (17 files total, no `hdl_interconnect/`, no sequences beyond the trivial
default ones) — its entire purpose is validating a `svt_usb_agent_configuration` object loaded
from a TEXT property file, not running any protocol traffic.

### 7a. test — `tests/ts.cfg_validate.sv` (`cfg_validate extends uvm_test`)
```systemverilog
function void build_phase(uvm_phase phase);
  svt_usb_agent_configuration cfg; cfg = new();
  super.build_phase(phase);
  if ($value$plusargs("validation_cfg_filename=%s", filename)) begin
    if (cfg.load_prop_vals(filename)) begin
      `uvm_info("my_info1", $psprintf("Successfully loaded ... using '%0s'.", filename), UVM_LOW)
      if (cfg.is_valid(0))
        `uvm_info("", $psprintf("... is valid."), UVM_LOW)
      else
        `uvm_error("my_info2", $sformatf("... is NOT valid."))
    end else
      `uvm_error("my_error1", $sformatf("Failed attempting to load ..."))
  end else
    `uvm_error("my_error2", "Filename ... not provided.");
endfunction
```
This is the ONLY place in the entire example set demonstrating
`svt_usb_agent_configuration::load_prop_vals(filename)` — the VIP's built-in mechanism to
deserialize a configuration object from a flat `key=value` text file at runtime, driven by a
`+validation_cfg_filename=<path>` plusarg (set in `sim_run_options`:
`` +UVM_TESTNAME=$scenario +validation_cfg_filename=${tbench_dir}/tests/usb_agent.cfg ``). No
UVM env/scoreboard/sequence is built at all — `top.sv` just instantiates `test_top` (module,
importing `svt_usb_uvm_pkg`) and calls `run_test()` directly against `cfg_validate`. This is the
canonical "config sanity check without a full testbench" pattern.

### 7b. configuration — `tests/usb_agent.cfg` (real property-file format, ~470 lines, `key=value`
one per line, `//` comments, grouped by originating class with `// ====` section headers). This
is the FULL FIELD INVENTORY of `svt_usb_agent_configuration` (protocol/link/physical layer
enables, SS timers, USB2.0 timers, endpoint config, host config) serialized as text — the single
richest raw enumeration of every configurable knob in the VIP found across the whole example
set. Structural notes worth citing verbatim:
- Per-object-array indexing syntax: `route_string_port[0]@local_device_cfg[0]=0`,
  `ep_number@local_device_cfg[0]:endpoint_cfg[0]=0` — i.e. `field@array_path[index]` for
  simple sub-object arrays, and `field@array_path[i]:nested_array[j]` (colon separator) for
  doubly-nested sub-object arrays (device config → its endpoint config array).
- `component_type=DEVICE`, `usb_capability=USB_SS_ONLY`, `speed=SS`,
  `usb_ss_signal_interface=USB_SS_TLM`, `usb_20_signal_interface=NO_20_IF`,
  `usb_ss_initial_ltssm_state=U0` — confirms enum values are written as their bare name strings
  (not integers) in the property-file format.
- Every SS LTSSM sub-state timeout appears as an explicit field:
  `polling_lfps_timeout=360.000000`, `polling_active_timeout=12.000000`,
  `hot_reset_active_timeout=12.000000`, `recovery_configuration_timeout=6.000000`,
  `u1_no_lfps_response_timeout=2.000000`, `u3_no_lfps_response_timeout=10.000000`, etc. — this
  file is a superset reference for exactly which LTSSM timers exist, useful cross-check against
  `usb_ess_pipe4_base_test.sv`'s narrower hand-tuned subset (§8).
- Full USB 2.0 electrical/protocol timing constants present too:
  `tdcnn_min/max`, `tdrst_min/max`, `tfilt_min`, `twtrev_min/max`, `tl1residency_min/max`
  (LPM L1 residency), `ta_srp_rspns_max`/`tb_srp_fail_min/max` (OTG SRP timing),
  `usb_20_hsic_*` (full HSIC strobe/connect/idle timing block) — i.e. HSIC electrical timing is
  a first-class, independently-configurable block even though no example directly builds an
  HSIC-speed test end-to-end (only `top.usb_20_hsic.sv`/`usb_20_hsic_dut*` exist as topology
  stubs in basic_program_sys/basic_sys).
- `local_device_cfg_size=1` at the top level but a SEPARATE, redundant-looking
  `local_device_cfg_exists[0]=1` flag later in the file — confirms the property-file format
  needs an explicit existence flag per array slot in addition to the size, presumably because
  `load_prop_vals` allocates the array from `_size` but only actually populates/validates slots
  flagged `_exists[i]=1`.
- `remote_host_cfg_exists=1` with a full nested `@remote_host_cfg` block
  (`five_gbs_speed_capable@remote_host_cfg`, `lpm_capable@remote_host_cfg=1`, etc.) — confirms a
  DEVICE-role config still carries a full remote HOST config block for validation purposes even
  though this cfg_validate test never builds an actual host agent.

### 7c. `env/usb_svt_shared_cfg.sv` — cross-referenced against `usb_shared_cfg.sv` used elsewhere
This file (used only by tests OTHER than `cfg_validate` in this same directory, e.g. if a
non-validator test were added) is structurally the SAME shared-cfg pattern as
`tb_usb_svt_uvm_20_phy`'s `usb_shared_cfg.sv` (host_cfg/dev_cfg pair, cross-linked
remote_device_cfg/remote_host_cfg, `setup_usb_{ss,ss_otg,20_otg,20}_defaults()` methods) but
**adds two methods not seen in the 20_phy version**: `setup_usb_ss_otg_defaults()` (SS+OTG
combined: `capability=OTG`, `micro_ab_plug_type=A/B`, `otg_capability=OTG_SS_CAPABLE`,
`ss_otg_issue_warm_reset=SS_OTG_IMMEDIATELY`, `t_reset_timeout=160us`,
`u3_no_lfps_response_timeout=100us`) and a parameterized
`setup_usb_20_otg_defaults(host_speed, dev_speed)` / `setup_usb_20_defaults(host_speed, dev_speed)`
that take explicit per-side speed arguments (defaulting to FS/FS and HS/HS respectively) rather
than hardcoding both sides to the same speed — i.e. this cfg class supports asymmetric
host/device speed test setups (e.g. HS host talking to FS device) that the plainer
`usb_shared_cfg.sv` in the phy-only examples does not expose as parameters. Also sets realistic
OTG SRP/ADP timing scaled down for simulation: `ta_adp_prb=1.75us` (spec nominal is much larger),
`tadp_rise=175ns`, `ta_vbus_rise=500ns` — the general pattern of "use spec-legal but
simulation-fast timing constants" for OTG/ADP tests.

---

## 8. tb_usb_svt_uvm_intermediate_sys — SuperSpeed PIPE3/PIPE4, hand-tuned LTSSM timers, real user coverage

Path: `D:\DV\Task\USB\VIP\examples\tb_usb_svt_uvm_intermediate_sys\`

The most valuable example for the COVERAGE aspect (the only one with a hand-written covergroup
extending the VIP's built-in coverage callback) and for PIPE3/PIPE4 interface + LTSSM timer
tuning.

### 8a. coverage — `usb_intermediate_protocol_ss_host_coverage_callbacks.sv` (THE reference
pattern for user-defined coverage layered on VIP-provided coverage)
```systemverilog
class usb_intermediate_protocol_ss_host_coverage_callbacks
    extends svt_usb_protocol_monitor_ss_host_def_cov_callback;
  int transfer_length = 0;
  covergroup user_defined_transfer_cover_group;
    transfer_type : coverpoint transfer_type {
      bins control = {svt_usb_transfer::CONTROL_TRANSFER};
      bins bulk_in = {svt_usb_transfer::BULK_IN_TRANSFER};
      bins bulk_out = {svt_usb_transfer::BULK_OUT_TRANSFER};
      option.weight = 0;
    }
    transfer_length : coverpoint transfer_length {
      bins min_length = {[0:8]};
      bins mid_length = {[9:512]};
      bins max_length = {[513:5000]};
      option.weight = 0;
    }
    transfer_type_X_transfer_length : cross transfer_type, transfer_length {
      ignore_bins control_max_length =
        binsof(transfer_type.control) && binsof(transfer_length.max_length);
    }
    option.per_instance = 1;
  endgroup

  function new(svt_usb_agent_configuration cfg = null);
    super.new("", cfg);
    user_defined_transfer_cover_group = new();
  endfunction

  function void sample_cov(coverage_enum coverage_type);
    super.sample_cov(coverage_type);              // let VIP sample its own built-in bins first
    user_defined_transfer_cover_group.sample();    // then sample the user covergroup
  endfunction

  function void transfer_ended(svt_usb_protocol_monitor protocol_mon, svt_usb_transfer xfer);
    transfer_length = xfer.payload_byte_count();   // capture the field the covergroup needs
    super.transfer_ended(protocol_mon, xfer);
  endfunction
endclass
```
Registered via `uvm_callbacks#(svt_usb_protocol_monitor)::add(host_agent.prot_mon, cb_for_host_cov)`
in `usb_intermediate_pipe4_env::build_phase` (note: attaches to `prot_mon`, i.e. the PROTOCOL
MONITOR, not the protocol driver/`prot` used for the transfer_observed_port and objection
callbacks — a third distinct attach point: `.prot` for driver-side callbacks,
`.prot_mon` for monitor/coverage callbacks, `.link`/`.downstream_agent[i].link` for link-layer
callbacks). The 3-step pattern (extend the VIP's `_def_cov_callback` base → override
`transfer_ended` to capture derived fields the built-in class doesn't expose as covergroup
inputs → override `sample_cov` to chain `super.sample_cov()` then sample your own group) is the
canonical way to ADD coverage without losing the VIP's built-in coverage model, and the
`ignore_bins` cross-exclusion (a CONTROL transfer can never be max_length given the payload
constraint applied elsewhere) demonstrates cross-bin pruning tied to a real protocol
constraint from `cust_svt_usb_transfer` (§1a: `payload_intended_byte_count_control_out <= 512`).
Coverage is only ACTUALLY collected if the config enables it: `build_phase` also sets
`this.cfg.host_cfg.enable_prot_cov = 1; this.cfg.host_cfg.enable_link_cov = 1;` — confirming
`enable_prot_cov`/`enable_link_cov` config fields gate whether VIP-internal coverage sampling
(and thus this callback's `sample_cov` invocation) happens at all.

### 8b. environment / interface — `usb_intermediate_pipe4_env.sv`: PIPE4 MAC-side remote_cfg pattern
Adds fields not seen in the simpler `usb_basic_serial_env`: `virtual svt_usb_if usb_ss_phy_if`,
`usb_ss_mac_if` (separate PHY-side and MAC-side interface handles — PIPE-interface testbenches
split the SS interface into two virtual interface handles because PIPE is a MAC↔PHY chip-to-chip
bus, unlike serial which is a single bidirectional differential pair), a `disable_scoreboard`
config bit (`` `uvm_field_int(disable_scoreboard, UVM_ALL_ON) ``) letting a test opt OUT of
scoreboard construction entirely, and the SAME remote_cfg-clone-as-PHY pattern seen in §5c but
gated specifically on `usb_ss_signal_interface == PIPE4_IF || PIPE3_IF` (vs. hub_basic_env's
gate which also included `UTMI_IF`) — i.e. remote_cfg cloning is required whenever EITHER side
of a link is a MAC-side PIPE/UTMI interface, regardless of topology complexity.
`connect_phase` connects the scoreboard DIRECTLY to the VIP's OWN analysis port
(`host_agent.prot.transfer_observed_port.connect(usb_scoreboard.host_export)`) — the simpler,
single-hop alternative to basic_router_sys's event-repolling `supply_analysis_ports()` indirection
(§5a) — confirming that direct analysis-port connection is sufficient/preferred whenever only
transfer-level (not transaction/packet-level) comparison across a SINGLE host/device pair is
needed.

### 8c. scoreboard — `usb_uvm_scoreboard.sv` (uses `uvm_in_order_comparator`, not a hand-rolled
queue+event loop)
```systemverilog
class usb_transfer_comp #(type T = int);
  static function bit comp(input T a, input T b);
    uvm_comparer relevant_comp_policy = new();
    relevant_comp_policy.physical = 1; relevant_comp_policy.abstract = 0; // RELEVANT policy
    return a.compare(b, relevant_comp_policy);
  endfunction
endclass

class usb_uvm_scoreboard extends uvm_scoreboard;
  uvm_analysis_export #(svt_usb_transfer) host_export, device_export;
  uvm_in_order_comparator #(svt_usb_transfer, usb_transfer_comp#(svt_usb_transfer),
                             uvm_class_converter#(svt_usb_transfer)) comparator;
  function void build_phase(uvm_phase phase);
    host_export = new(...); device_export = new(...); comparator = new("comparator", this);
  endfunction
  function void connect_phase(uvm_phase phase);
    host_export.connect(comparator.before_export);
    device_export.connect(comparator.after_export);
  endfunction
  function void report_phase(uvm_phase phase);
    `uvm_info(..., $psprintf("Matches = %0d, Mismatches = %0d", comparator.m_matches, comparator.m_mismatches), UVM_NONE);
    if (comparator.m_mismatches != 0) `uvm_error("Scoreboard Report","TEST FAIL");
    else `uvm_info("Scoreboard Report","TEST PASS",UVM_NONE);
  endfunction
endclass
```
This is the SIMPLEST of the three distinct scoreboard architectures found across the example set
(vs. hand-rolled dual-queue+event in §5b's transaction/packet scoreboards) — it delegates
ordering/matching entirely to UVM's built-in `uvm_in_order_comparator`, which assumes host and
device transfers arrive in the SAME relative order on both sides (no endpoint/address
re-matching search needed) and simply diffs `before_export` against `after_export` pairwise via
the injected static `comp()` function. **Cross-reference**: this is the RIGHT choice only for
simple single-host/single-device transfer-level comparison; basic_router_sys's hub scoreboards
(§5b) needed the hand-rolled search-based approach specifically because packets/transactions
from MULTIPLE devices/hubs interleave out of strict host-issue-order on the wire.

### 8d. test / configuration — `usb_ess_pipe4_base_test.sv`: extensive hand-tuned LTSSM timer set
Beyond the standard `setup_usb_ssp_defaults()` + `PIPE4_IF`/`USB_SS_TLM` interface split
(`cfg.host_cfg.usb_ss_signal_interface = PIPE4_IF; cfg.dev_cfg.usb_ss_signal_interface =
USB_SS_TLM;` — confirming host is the MAC/PIPE side, device is the abstract TLM side in this
topology), this test explicitly overrides ~40 individual LTSSM-related timer/count fields
(`receiver_detect_time`, `rx_detect_quiet_timeout`, `rx_detect_termination_detect_count`,
`p2_to_p0_transition_time`, `tx_lfps_duty_cycle`, `polling_lfps_burst_time`,
`polling_lfps_sent_count`, `polling_lfps_sent_after_received_count`, `polling_active_received_ts_count`,
`polling_configuration_{received,sent}_ts2_count`, `polling_idle_{received,sent}_idle_count`,
`ltssm_skip_polling_rxeq`, `polling_rxeq_{,ssp_}tseq_count`) with host and device
INTENTIONALLY set to DIFFERENT values for the same logical parameter (comment: *"Host and
Device VIPs' timers are intentionally programmed to different values to demonstrate VIP's usage
that suits DUT's timers"*) — i.e. this is the reference pattern for a generation agent needing
to model a real DUT's asymmetric PHY timing (host side representing the DUT's actual timing,
device side representing the VIP's own tunable receive/transmit windows) rather than assuming
symmetric host/device VIP timing is required. Also sets
`cfg.host_cfg.usb_ss_automatic_lmp_disable = 1; cfg.dev_cfg.usb_ss_automatic_lmp_disable = 1;`
specifically so the test can exit "right after both Host and Device reach U0 ltssm state"
without the VIP auto-exchanging port-capability/port-configuration LMPs — a useful knob for
tests that only care about LTSSM training completion, not post-U0 link management.
`main_phase` starts a `usb_device_response_sequence` on `env.dev_agent.xfer_response_sequencer`
(a RESPONSE sequencer, distinct from the xfer_sequencer used for host-initiated transfers —
confirms devices have a separate sequencer specifically for reactive/response sequences) then
blocks on `wait(env.host_agent.shared_status.ltssm_state == svt_usb_types::U0);
wait(env.host_agent.shared_status.lmp_generation_completed_status == svt_usb_types::NORMALLY);`
— i.e. `shared_status` exposes both LTSSM state AND an LMP-generation-completion status field.

### 8e. sequence — `usb_ltssm_sequence.sv`: minimal manual LTSSM kick-off via link_service
```systemverilog
class usb_ltssm_sequence extends uvm_sequence#(svt_usb_link_service);
  svt_usb_agent_configuration host_cfg;
  task body();
    svt_usb_link_service link_service_command = new("link_service_command");
    uvm_config_db#(svt_usb_agent_configuration)::get(null, get_full_name(), "host_cfg", host_cfg);
    link_service_command.service_type = svt_usb_link_service::LINK_SS_PORT_COMMAND;
    link_service_command.link_ss_command_type = svt_usb_link_service::USB_SS_POWER_ON_RESET;
    link_service_command.prereq_ltssm_state = svt_usb_types::SS_DISABLED;
    link_service_command.cfg = this.host_cfg;
    `uvm_send(link_service_command)
  endtask
endclass
```
Confirms: LTSSM state transitions on the HOST side are driven via `svt_usb_link_service` items
(a THIRD distinct sequence-item type beyond `svt_usb_transfer` and `svt_usb_protocol_service`,
sent to a link-service sequencer) carrying a `prereq_ltssm_state` guard field — i.e. the VIP
will only execute the command once the LTSSM has reached (or is already at) the stated
prerequisite state, which is how sequences can be fired "early" and let the VIP itself
gate execution on protocol state. Per USB3 spec comment: device-side SS.Disabled→Rx.Detect does
NOT require an explicit command (only host/downstream-facing ports do), confirming host and
device LTSSM entry are asymmetric even at the very first state transition.
