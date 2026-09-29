# Category 5 Extraction: DWC_usb31 IP Documentation (User Guide / Databook / Install / Release Notes)

Extraction date: 2026-09-03. Source root: `D:\DV\Task\USB\DOC\` and `D:\DV\Task\USB\DOC\IP\`.
IP: Synopsys DesignWare Cores Enhanced SuperSpeed USB 3.1 Controller (`DWC_usb31`), **Version 2.10a, January 2024**
(this is the version stamped on every real document below — user guide, databook, install guide, release notes all
agree on "Version 2.10a / January 2024").

## 0. Source inventory and access notes

| # | File | Path | Format read | Status |
|---|------|------|-------------|--------|
| 1 | User Guide | `D:\DV\Task\USB\DOC\IP\DWC_usb31_user.txt` (+ `.pdf`) | plain text, 9379 lines, already pre-extracted | OK, read directly |
| 2 | Databook | `D:\DV\Task\USB\DOC\IP\DWC_usb31_databook.txt` (+ `.pdf`) | plain text, ~23,900+ lines, already pre-extracted, v2.10a Jan 2024 | OK, read directly |
| 3 | Databook (top-level) | `D:\DV\Task\USB\DOC\DWC_usb31_databook_WM-25380.pdf` | N/A | **INACCESSIBLE** — this PDF is password-encrypted (`pdftotext` returns "Incorrect password"; `pypdf` confirms `is_encrypted=True` and empty-string decrypt fails; `pymupdf`/fitz reports "corrupt object stream" and 0 pages). Could not extract any content. Given the near-identical file size (5,902,096 bytes vs 5,852,826 bytes for the IP-folder databook) and identical product name, this is almost certainly a watermarked (WM-25380 = watermark ID) copy of the same Databook content already available unencrypted at item #2. **All Databook facts in this report are sourced from item #2, not this file.** Flagging this as an intake gap in case the watermarked copy is later needed for a different reason (e.g., audit trail of who downloaded it). |
| 4 | Install Guide | `D:\DV\Task\USB\DOC\IP\DWC_usb31_install.pdf` | converted via `pdftotext -layout` (no pre-existing .txt) | OK, 1378 lines extracted |
| 5 | Release Notes | `D:\DV\Task\USB\DOC\IP\DWC_usb31_relnotes.pdf` | converted via `pdftotext -layout` | OK, 383 lines extracted, single chapter |
| 6 | Link block register extract | `D:\DV\Task\USB\DOC\IP\link_block_extract.txt` | plain text, 534 lines | OK — this is itself a derived extract (its `=== NAME (lines N-M) ===` headers cite line numbers into the Programming Guide, `DWC_usb31_programming.txt/pdf`, lines ~20573-24000, which is a different category's source and not re-read here) |

Also present but out of scope for this category (belongs to programming/register category): `DWC_usb31_programming.txt/pdf`.

---

## 1. User Guide (`DWC_usb31_user.txt`) — coreConsultant configuration & simulation flow

This document is **not** where the parameter *definitions* live (port count, endpoint count, etc. — those are in
the Databook, Chapter 4, see §2 below). The User Guide explicitly says so:

> "For more information about the configuration parameters, see 'Parameter Descriptions' chapter of the DWC
> Enhanced SuperSpeed USB 3.1 Controller Databook." (line 942-944)

What the User Guide *does* own is the **process** of turning parameters into RTL/verification collateral, via the
Synopsys `coreConsultant` GUI tool, and the structure of the **PVE testbench** used to simulate the configured
core.

### 1.1 Configuration flow (Chapter 2, "Configuring the Controller", lines ~900-1250)

- Step 1 "Specify your configuration" in coreConsultant's **Specify Configuration** activity — sets feature
  enables, memory sizes, and CSR power-on default values. coreConsultant enforces parameter interdependencies
  live (e.g., selecting Device mode auto-disables all Host-only parameters) (line 948-950).
- Step 2 "Generate RTL" — click Apply; RTL lands in `workspace/src/`.
- Step 3 generates configuration reports (Report tab) and optional "Activity Specific Reports/Views" — e.g. an
  example component instantiation view.
- **`workspace/src/DWC_usb31_params.v`** is called out (line 4828 of the Databook, but referenced from this flow)
  as the file holding non-coreConsultant-exposed parameter values.

### 1.2 Prime Profiles (§2.2.1, lines 995-1109) — new in 2.10a

This is a version-specific new feature (added in 2.10a per Revision History, line ~239) worth flagging to a
generation agent because it changes how a target configuration is normally selected:

- A **Prime Profile** is a pre-defined, application-focused parameter bundle that locks most parameters to
  known-good, pre-verified combinations, to avoid "inadvertent selection of a non-verified crossing of
  configuration parameters" (line 997-999).
- Table 2-1 (line 1016) lists three commonly-available Prime Profiles for DWC_usb31 (availability depends on
  purchased licenses):
  - **PP_DRD_VTIO_EXTCGTU0_ISOCINQPT** — USB31 DRD, VTIO, Hibernation enabled with Async PMU, External Clock
    Gating U0 enabled, ISOC IN QPT enabled.
  - **PP_HST_EXTCGTU0_ISOCINQPT_SINGLEPORT** — USB31 single-port Host, Hibernation with Async PMU, External
    Clock Gating U0, ISOC IN QPT enabled.
  - **PP_HST_VTIO_EXTCGTU0_ISOCINQPT_SINGLEPORT** — USB31 single-port Host, VTIO, Hibernation with Async PMU,
    External Clock Gating U0, ISOC IN QPT enabled.
- **Analysis Mode**: unlocks the profile's locked parameters for inspection but **RTL generation is disallowed in
  Analysis Mode** (line 1080) — coreConsultant only emits a batch script (to `workspace/export`) meant to be sent
  to Synopsys Support, not used for a real build.
- **External Prime Profiles**: `.pp.gz` files usable via a `<custom>` option, for special support engagements
  (§2.2.1.3, line 1098-1110).
- Practical implication for a generation/config agent: if a target config matches one of the above Prime
  Profile categories (DRD+VTIO+Hibernation, or single-port Host+Hibernation, optionally +VTIO), the
  Synopsys-recommended/pre-verified path is to select the Prime Profile rather than hand-picking every Basic/PHY/
  Device/Host/Advanced parameter from scratch — because non-Prime-Profile parameter *crossings* are, by
  Synopsys's own description, less verified.

### 1.3 PVE Testbench structure (§3.1, lines ~1700-2400+)

The PVE (Pre-Verified Environment) is the UVM-based SoC-integration-example testbench that ships with the core
and that coreConsultant drives.

- **VIP components used**: AHB Requester/Completer VIP, AXI Requester/Completer VIP (both DW AMBA VIP), plus
  two PHY models:
  - Synopsys USB 3.1 PHY model — drives `pipe_clk`, connects to PIPE3/PIPE4, runs USB 3.1 and USB 3.0 serial
    tests. Third-party PHY substitution is via a custom `ess_phy.f` filelist selected in coreConsultant's
    "Setup and Run Simulation → Testbench" tab (line 1786-1792).
  - Synopsys USB 2.0 GTECH PHY — drives `utmi_clk`, supports UTMI+ and ULPI (via a ULPI2UTMI adapter). Custom
    filelist: `dwc_usb20_phy_1p_ms_otg0_ns_inst.f` (line 1794-1800).
- **Testbench file locations** (Table 3-1, line 1841-1949): `Workspace/sim/Soc_sim/utb/{com,device,device/tests,
  host,host/tests}`. Notable files: `test_top.v` (top level), `DWC_usb31_SOC_wrapper.v`, `DWC_usb31_clocks.v` /
  `DWC_usb31_resets.v`, `runsim_vcs` (VCS compile/run script), `DWC_usb31_app_if.v` (UVM↔HDL interface bridge on
  the application side), `DWC_usb31_vip_interconnect.v` (feed-through interconnect UVM↔USB side),
  `usb31_tca_apb_sequence_collection.sv` (APB sequence for the Type-C Assist module on the Synopsys PHY),
  `utb_iip_dut_dwc_usb31_test_suite_configuration.sv` (extended test-suite config for flexible endpoint
  configuration), `DWC_usb31_utb_ctrl_phy.upf` / `DWC_usb31.upf` (UPF power-intent files for controller+PHY).
- **Test naming convention** (Table 3-2, line 2012 onward): device-mode tests are named
  `usb_20_na_31_ssp_<transfer-type>[_<qualifier>]`, e.g. `usb_20_na_31_ssp_bulk_in`,
  `usb_20_na_31_ssp_bulk_out_with_payload_size_256k`, `usb_20_na_31_ssp_iso_in/out`,
  `usb_20_na_31_ssp_ltssm_u0_to_u3_to_u0`, `usb_20_na_31_ssp_control_read/write` — i.e.
  `<usb2-role>_na_<usb31-speed>_<test content>`; "SSP" = SuperSpeedPlus (Gen2). A parallel Table 3-3 (line 2179)
  covers Host-mode tests, Table 3-4 (line 2365) covers combined Host+Device tests. coreConsultant right-click on
  a test shows its enabling condition against the chosen configuration parameters (line 1998-1999).
- Separate sub-testbenches exist for **EUSB2** (§3.1.5/3.1.6/3.1.7, lines ~93-101 pages) and **ROUTERIF**
  (§3.1.8/3.1.9/3.1.10, lines ~102-114 pages) configurations — each with its own file list and test list, because
  (per Release Notes, see §4.2 below) "Multi-port and Router configurations do not support eusb2 tests."
- This chapter (PVE testbench) is the User-Guide-side counterpart to whatever the VIP-docs category extracts
  from the Verification IP itself — cross-reference if that category's extraction covers `USB_SVT`/`AMBA_SVT`.

---

## 2. Databook (`DWC_usb31_databook.txt`, v2.10a Jan 2024) — the real parameterization surface

This is the authoritative source for IP-generation-time configuration. Chapter 4 "Parameter Descriptions"
(line 4795 onward) is organized into 8 tables (line 4837-4844):

`ROUTERIF-CIO Config` (4.1) → `CIO Config` (4.2) → `Basic Config` (4.3) → `PHY Config` (4.4) →
`Device Config` (4.5) → `Host Config` (4.6) → `Advanced Config` (4.7) → `Register Power-On Value Parameters` (4.8)

Every parameter entry in the Databook gives: Label, Description, Values (legal set/range), Default Value
(often a `<functionof>` TCL-style conditional expression on other parameters), an `Enabled:` boolean expression
(when the parameter is exposed/settable), and a `Parameter Name:` (the literal Verilog macro/parameter, always
prefixed `DWC_USB31_`). Section line numbers below are into `DWC_usb31_databook.txt`.

### 2.1 Mode of operation and product-code license gating (Basic Config, §4.3, line 4902-4954)

- **`DWC_USB31_MODE`** (line 4910-4924): `Device(0) / Host(1) / DRD(2) / Reserved(3)`. Default is computed from
  which license feature-authorize flags are true: Device-only license → 0, Host-only → 1, `<DWC-USB31-HUB-SRC
  feature authorize>` → 3 (Reserved/Hub), else → 2 (DRD). This is the single top-level fork controlling almost
  every other Enabled: expression in the chapter.
- **`DWC_USB31_EN_PWROPT`** (line 4926-4954): `No Power Optimization(0) / Clock Gating Only(1) / Clock Gating +
  Hibernation-Two-Power-Rail(2)`. Hibernation (value 2) requires the **`DWC-USB31-2PWR`** add-on license.
  Default = 1 (Clock Gating Only), gated by `DWC_USB31_MODE != 3`.
- **`DWC_USB31_ASYNC_PMU`** (line ~4985): when Hibernation is used, whether the PMU and controller clocks are
  treated as asynchronous (adds `core_pipe_pclk`/`core_utmi_clk`/`core_ulpi_clk` inputs and clock-crossing
  ring buffers/FIFOs). Note: "16-bit UTMI does not meet USB turnaround timing if this parameter is enabled — must
  enable this parameter only in 8-bit UTMI mode" (line 4973-4974) — a real constraint a config-generation agent
  must respect.

### 2.2 Port count and speed capability (Host Config, §4.6, line 6164-6500)

| Parameter | Range | Default | Notes / Enable condition |
|---|---|---|---|
| `DWC_USB31_HOST_NUM_U2_ROOT_PORTS` (line 6369-6374) | 1–15 | 1 | "Number of USB 2.0 (HS/FS/LS) Root Hub ports." ~12K gates/port. `Enabled: DWC_USB31_MODE==1` (Host mode text says Host, but see Host-Multi-Port product code — DRD is single-port only, see §2.7). |
| `DWC_USB31_HOST_NUM_U3_ROOT_PORTS` (line 6376-6383) | 1–4 | `(MODE==3) ? (HUB_NUM_U3_PORTS+1) : 1` | "Number of USB 3.1 ESS Root Hub ports." ~52K gates/port. Enabled only when `MODE==1 && EN_USB2_ONLY==0 && EN_ROUTERIF==0`. |
| `DWC_USB31_NUM_HS_USB_INSTANCES` (line 6392-6408) | 1–4 | 1 | Number of concurrent HS (480 Mbps) bus instances; "cannot be greater than USB 2.0 Root Hub ports" — explicit cross-parameter constraint. 4 ports + 4 instances ⇒ 1.92 Gbps aggregate concurrent HS throughput. ~55K gates/instance. |
| `DWC_USB31_NUM_DEVICE_SUPT` (line 6410-6430) | 64 or 127 | 64 | "Number of Devices Supported" — memory-only cost (32 bytes internal RAM/device), no gate-count impact. Reference point: USB-IF Gold Tree host-compliance topology = 19 devices (9 hubs, 2 webcams, 1 printer, 2 keyboards, 3 mass-storage, 1 mouse, 1 headset). |
| `DWC_USB31_HOST_NUM_INTERRUPTER_SUPT` (line 6345-6367) | 1–8 | 1 | 100 bytes internal RAM/interrupter; note "**Some Operating systems may require a minimum of 3 interrupters**" (line 6358-6359) — a real OS-driver-compatibility constraint. |
| `DWC_USB31_HOST_NUM_PERIODIC_EP` (line 6438-6471) | 32–510 | 32 | Total periodic EPs across ESS+HS+FS/LS combined; 20 bytes RAM/EP. Databook explicitly recommends **64** (not the 32 default) for Gold Tree host-compliance testing because that topology can exceed 32 periodic endpoints (line 6448-6453). |
| `DWC_USB31_NUM_HEPH_PER_SS_BI` / `..._PER_HSFSLS_BI` (line 6473-6500) | 1–4 | 3 (SS) / 1 (HS/FSLS) | Endpoint handlers per bus instance (fetch TRBs, R/W EP context, generate events). |

Feature-level summary from Chapter 1 (§1.2.4 "USB 3.1 xHCI Host Features", line 1760-1822):
- "Up to 127 devices", "Up to 8 interrupters", "**Up to 15 USB 2.0 ports and 4 Enhanced SuperSpeed ports**", "Up
  to four SuperSpeed bus instances, four high-speed bus instances, and one full-speed/low-speed bus instance."
- xHCI **1.2** compatible, with explicit non-conformance carve-outs: I/O Virtualization, Message Interrupt,
  Extended Message Interrupt, Local Memory, Get Port Bandwidth, Get/Set Extended Properties Command, and xHCI
  Audio Sideband are **not supported** (line 1770-1772) — repeated and detailed in §2.9 below.
- Event Ring Segment Table max 15 entries (`DCERST_Max = 15`) (line 1795).
- Required license: `DWC-USB31-HST-SRC`; `DWC-USB31-LPDDR4-QOS` add-on needed for LPDDR4 retraining QoS feature
  (line 1798-1800).

### 2.3 Speed-capability parameters (mode fork; cross-referenced against §2.9 unsupported list)

- **`DWC_USB31_SSPHY_INTERFACE`** (line 5454-5467): `None(0) / PIPE3(1) / PIPE4(2)`. "If you are planning to use
  only USB 3.0 mode, select PIPE3 or PIPE4. In USB 3.1 mode, select PIPE4." Default depends on
  `EN_USB2_ONLY`/`EN_USB30_ONLY` flags.
- **`DWC_USB31_EN_5GBS`** (line 6224-6238, labeled "Enable 5GB PSI only Advertisement"): advertises `PSIC=1`
  and only the 5 Gb/s Protocol Speed ID in the extended-capability register — "Enable this parameter if you plan
  to use the USB 3.1 controller in USB 3.0 mode only (no SSP) and connect it to a USB 3.0 PHY." Gated on
  `EN_USB30_ONLY==0 && EN_USB2_ONLY==0`.
- **`DWC_USB31_EN_USB2_ONLY`** and **`DWC_USB31_EN_USB30_ONLY`**: these two flags are referenced pervasively as
  gating/default-selection terms throughout Chapter 4 (over 30 references — Bus width defaults, endpoint FIFO
  depth defaults, PIPE interface enable, etc.) but **no `Parameter Name:` definition block for either flag
  appears in the extracted Chapter 4 text** — i.e., they read as coreConsultant-internal/product-code-derived
  switches rather than a Basic-Config GUI checkbox with its own Values/Default/Enabled block. **Cross-reference
  finding**: §1.5 "Unsupported Features and Usage Restrictions" (line 2040-2053) explicitly lists **"USB
  3.0-only mode"** and **"USB 2.0-only mode" as Unsupported Configurations** in this 2.10a release. So although
  the formulas throughout Chapter 4 are written generically to handle `EN_USB2_ONLY=1` / `EN_USB30_ONLY=1`, the
  *actual currently-supported/verified* product configurations always leave both at 0 (full USB 3.1 dual-speed
  operation). A verification/config-generation agent should treat any request for a USB-2-only or
  USB-3.0-only-mode configuration as **out of the currently supported/verified envelope** for this exact IP
  version, even though the parameter machinery nominally supports it.
- General feature list (§1.2.1, line 1510-1543) states operation modes as: **SSP (10 Gbps), SuperSpeed
  (5 Gbps), high-speed (480 Mbps), full-speed (12 Mbps), low-speed (1.5 Mbps)** — and explicitly: **"Low-speed
  mode is not supported in Device mode"** (line 1514).
- 10 Gbps figure specifically: Device mode claims "10 Gbps IN and 10 Gbps OUT bandwidth (interpacket delays and
  protocol overhead included)" (line 1692); Host mode claims "Concurrent SuperSpeedPlus IN and OUT transfers to
  get the full 19.4 Gbps duplex throughput" and, in a 4-port/4-bus-instance config, "net throughput is 77.6 Gbps
  (4 * 9.74 Gbps IN and 4 * 9.74 Gbps OUT)" (line 1783-1793).

### 2.4 Device endpoint count parameterization (Device Config, §4.5, line 5750-6163) — the core "endpoint count limit" answer

- **`DWC_USB31_NUM_EPS`** ("Number of Device Mode Endpoints (4-32)", line 5794-5824): total number of
  single-directional device-mode endpoints, **including control OUT/IN EP0 which are always present**.
  - `Values: ((MODE==3) ? 3 : 4), ..., 32` — i.e. minimum is 3 in Hub/Reserved mode, 4 otherwise.
  - `Default: ((MODE==3) ? 4 : 8)` — the default of 8 explicitly models a UASP mass-storage + ISOC use case:
    Control-OUT, Control-IN, Bulk-Data-OUT, Bulk-Data-IN, Bulk-Command-OUT, Bulk-Status-IN, ISOC-OUT, ISOC-IN
    (line 5809-5817).
  - Cost: **"2.5/3.5 Kgates" per OUT/IN endpoint** plus transfer-resource cache (line 5818); over-provisioning
    costs gates with no performance benefit (line 5801-5804).
  - Endpoints are dynamically remappable: "During coreConsultant configuration, you can configure n number of
    endpoints, and post-silicon, software can map the USB endpoint to an endpoint resource number, even if the
    USB endpoint numbers are not contiguous" (line 1687-1689, feature list).
- **`DWC_USB31_NUM_IN_EPS`** ("Number of Device Mode Active IN Endpoints (2-16)", line 5826-5841): max
  simultaneously-active IN endpoints (incl. control IN0), determines number of Device TxFIFOs/Tx RAM
  instantiated. `Values: 2..16`, `Default: (MODE==3) ? 2 : 4`.
- Feature-list cross-reference (§1.2.3, line 1682): "**Up to 16 bidirectional endpoints, including control
  endpoint 0**" — this is the headline number in the Product Overview chapter and is consistent with
  `NUM_IN_EPS` maxing at 16 (bidirectional capacity is bounded by the IN-endpoint cache/FIFO resource, since
  `NUM_EPS` maxes at 32 single-directional = 16 pairs).
- **`DWC_USB31_CACHE_TRBS_PER_TRANSFER`** (line 5850-5872): 4–32, default 16; TRB cache cost = 16 bytes ×
  count. Explicit worked guidance: scatter-gather across 8×128-byte buffers in a 1KB packet needs ≥9 TRBs cached
  (8 data + 1 Link); recommends also enabling
  `DWC_USB31_DEV_EN_SCATTER_PACKETS_OF_8_TO_15_TRBS` (Advanced Config) alongside external buffer control.
- **`DWC_USB31_DEVICE_NUM_INT`** ("Number of Device Mode Event Buffers (1-32)", line 5758-5788): 1–32, default 1.
  Multi-interrupt use case is multi-core SoC load-balancing; "the Synopsys mass-storage BOT and UASP reference
  driver supports only one interrupt" (line 5779) and "In device mode, dynamic mapping of an interrupt is not
  supported" — static mapping only, done at endpoint-config time (line 5774-5776).
- **`DWC_USB31_EXT_BUFF_CONTROL`** (line 5852-5887): External Buffer Control (EBC) sideband signals
  (`dev_usb_outep_pkt_buff_avail`/`dev_usb_inep_pkt_buff_avail`); "mainly used for debug endpoints and has usage
  restrictions" — see Appendix F "EBC and MIPI Gigabit Debug".

### 2.5 System bus interface parameters (Basic Config §4.3 continued + PHY Config §4.4, line 4956-5470)

- **`DWC_USB31_SBUS_TYPE`** (Completer/register bus): `AHB(0) / AXI(1) / Reserved-1(2) / Reserved-2(3)`,
  default AXI (line 5057-5074).
- **`DWC_USB31_MBUS_TYPE`** (Requester/DMA bus): `AHB(0) / AXI(1) / Native(3)` — **"Native interface is not
  supported in this release. If you are interested in this interface, contact Customer Support"** (line
  1612-1613), reconfirmed in §2.9 Unsupported Configurations ("Native interface", line 2046).
- **`DWC_USB31_AWIDTH`** (address width): 32 or 64 bits, default 32 (line 5010-5027).
- **`DWC_USB31_SDWIDTH`** (completer/register data width): 32/64/128 bits, default 32 (line 5076-5086).
- **`DWC_USB31_MDWIDTH`** (requester/DMA data width): options listed as `Reserved-1(32) / Reserved-2(65) /
  64 bits(64) / 128 bits(128)`, default 64 (line 5104-5117). **Cross-reference finding**: §2.9 Unsupported
  Configurations explicitly lists **`DWC_USB31_MDWIDTH=32`** as unsupported (line 2045) — matching the table's
  own "Reserved-1 (32)" labeling of that value; i.e. 32-bit requester data width is nominally selectable in the
  parameter's Values list but is a reserved/unsupported combination in this release, not a functioning option.
- AHB completer/requester and AXI completer/requester interface capability details (protocol conformance,
  burst-type support, ordering rules) are enumerated in §1.2.2.1–1.2.2.5 (line 1573-1678) — e.g. AXI
  Requester: "Supports out-of-order data transfers between two different IDs; does not support out-of-order
  data transfers within the same ID," "zero-wait state data transfers," 4K-boundary splitting, optional 1K
  breakup via `GSBUSCFG1`.
- **PIPE data width**: Chapter 1 note "Doc: DWC_usb31 controller supports only 32-bit mode of operation on USB3
  PIPE Interface" appears as a *documentation fix* in Release Notes 2.10a changelog (relnotes.txt line 150), and
  §2.9 confirms as a real restriction: **"8-bit and 16-bit PIPE Data widths (Only 32-Bit PIPE Data Width is
  supported)"** (databook line 2056).
- **`DWC_USB31_PCLK_AS_PHY_INPUT`** (line 5439-5450): `PCLK AS PHY OUTPUT (C10 PHY) (0)` vs `PCLK AS PHY INPUT
  (C20 PHY) (1)` — set to 1 only with Synopsys C20/C40 PHY.

### 2.6 Advanced/Premium (EA) host features gated by license (Host Config §4.6, line 6170-6337)

Grouped under a "Premium New Features (EA)" heading — i.e. these require the `DWC USB 3.1 Host Premium`
(`I601-0`) / `DWC USB 3.1 DRD Premium` (`I600-0`) product, and are labeled EA (Early Access):

- **`DWC_USB31_VTIOC`** — "Enable xHCI VTIO Capability" (Virtualization-based Trusted IO). Note from Release
  Notes: **"VTIO not supported and should not be enabled in DWC_usb31 2.00a"** (relnotes.txt line 131) — i.e.
  this is a feature that only became usable starting with a later version than 2.00a (2.10a fixed a "VTIO
  Feature Enhancement", relnotes.txt line 128); a verification agent targeting anything before that fix should
  not assume VTIO works.
- **`DWC_USB31_EXT_BUS_CLK_OFF_FC`** — shuts down `bus_clk_early`'s reference PLL when only interrupt-IN
  endpoints are active/flow-controlled (EA).
- **`DWC_USB31_ISOC_QUIET_DMA`** — "Enable isoc coalescing feature (EA Feature)": enters a DMA quiet period
  while buffering ISOC IN packets before opening the DMA — described further in Appendix D "ISOC Coalescing".
- **`DWC_USB31_EN_DBC`** — xHCI Debug Capability (DbC); requires `MDWIDTH != 32` and `EN_USB2_ONLY==0`.
- **`DWC_USB31_LPDDR4_QOS`** — Periodic-Transfer QoS support for LPDDR4 SoCs; requires the
  `DWC-USB31-LPDDR4-QOS` add-on license (`<DWC-USB31-LPDDR4-QOS feature authorize>` in the Enabled: expr, line
  6306). Worked sizing example given: to support a 20 µs DMA block-out time you need "at least 32 ESS Cache,
  24-packet ESS Rx/Tx FIFOs, 3-packet HS Rx/Tx FIFOs, and 2-packet FS/LS Rx/Tx FIFOs" (line 6292-6295).
- **`DWC_USB31_PCIE_L1_WAKEUP`** — EA feature managing PCIe L1-exit latency (up to 100 µs) so periodic host
  transfers are still serviced on time.
- **`DWC_USB31_NUM_PTLHRXE` / `DWC_USB31_NUM_PTLHTXE`** — number of concurrent IN/OUT transfers supported in SSP
  mode (1–4 each); large area overhead per additional concurrent transfer; both gated on an internal
  `DWC_USB31_CURRENT_GEN_HST_LSP==2` condition (see note below) plus `EN_USB30_ONLY==0 && EN_USB2_ONLY==0`.

**Inferred cross-reference (not explicitly spelled out in the extracted text, flagged as inference)**: the
internal switch `DWC_USB31_CURRENT_GEN_HST_LSP` (referenced ~15 times across Host Config defaults/enables, e.g.
line 5001, 6245, 6257, 6624/6653/6732/6812/6887/6967, but with no `Parameter Name:` definition block of its own in
the extracted Chapter 4 — it looks like an Appendix I "Internal Parameter" set from the license/product tier) sets
the ceiling on Host-mode link generation: `==2` unlocks 4-concurrent-transfer SSP/Gen2 behavior and shows up
exactly in the same "Premium New Features" grouping as VTIO/DbC/LPDDR4-QoS. Given the Product Codes table lists a
plain `DWC USB 3.1 Host-Multi Port` (A872-0) alongside a separate `DWC USB 3.1 Host Premium` (I601-0), it is
reasonable (but not textually proven in the extracted material) that `CURRENT_GEN_HST_LSP==2` correlates with the
Premium license tier while `==1` is the base tier. A verification engineer relying on this should confirm against
Appendix I "Internal Parameter Descriptions" (databook page ~513, not captured verbatim in this extraction pass)
before treating it as fact.

### 2.7 Product codes and license-to-configuration mapping (Preface, line 946-971; repeated in Install Guide and Release Notes)

| Product / Add-on | Code |
|---|---|
| DWC USB 3.1 Device | A868-0 |
| DWC USB 3.1 Host-Single Port | A869-0 |
| DWC USB 3.1 Host-Multi Port | A872-0 |
| DWC USB 3.1 DRD-Single Port | A871-0 |
| DWC USB4 DRD1Port10GPipeSRtrIF | E873-0 |
| DWC USB 3.1 Hibernation Add-On | A875-0 |
| DWC USB 3.1 Host-Multi Port Add-On (upgrade path from Host-Single-Port) | A870-0 |
| DWC USB 3.1 LPDDR4 QoS Add-On | C193-0 |
| DWC USB 3.1 DRD Premium | I600-0 |
| DWC USB 3.1 Host Premium | I601-0 |

**Cross-reference / consistency check**: note there is **no "DRD-Multi Port" base product** in this table — only
DRD-**Single**-Port exists. This is fully consistent with §1.5 Unsupported Configurations explicitly listing
**"Multi-Port DRD"** as unsupported (databook line 2042). The product catalog and the unsupported-features list
agree with each other, which is a useful sanity confirmation for a config-generation agent: never emit a
DRD config with `HOST_NUM_U3_ROOT_PORTS`/`HOST_NUM_U2_ROOT_PORTS` > 1 when `DWC_USB31_MODE==2` (DRD).

Required-license mapping (Install Guide Table 1-4, install.txt line 379-397, matches Databook §1.2.3-1.2.5):
- Device: `DWC-USB31-DEV-SRC`.
- Host: `DWC-USB31-HST-SRC` (+ `DWC-USB31-HOSTMP` for multi-port).
- DRD: `DWC-USB31-DEV-SRC` + `DWC-USB31-HST-SRC`.
- Add-ons: Hibernation → `DWC-USB31-2PWR`; Host-Multi-Port add-on → `DWC-USB31-HOSTMP`; LPDDR4 QoS →
  `DWC-USB31-LPDDR4-QOS`; Premium → `DWC-USB31-V2`.
- VIP licenses (separate): `VIP-USB3-SVT`, `VIP-AMBA-AXI-SVT`, `VIP-AMBA-AHB-SVT`, `VIP-USB31-IIPPACK`,
  `VIP-USB-31-OPT-SVT`.
- Tool: `DWC-coreAssembler`.
- Base install itself needs a `DWC-USB31` license, and either Project-ID-based access (for unencrypted RTL) or
  encrypted-source-only access without a PID (install.txt Table 1-3, line 362-377).

### 2.8 Full feature list (Chapter 1 "Product Overview", §1.2, line 1503-1998)

Organized by the Databook itself into subsections — this is the authoritative feature list, not a paraphrase:

- **§1.2.1 General Features** (line 1508-1543): 5 speed modes (see §2.3 above); same programming model across
  speeds; Streams with flexible allocation; 1–16 burst; internal DMA; LPM in USB2 and U0/U1/U2/U3 for USB3.1;
  **hardware-controlled LPM in USB 2.0 host** (host autonomously detects idle downstream port and issues LPM
  token, host-only feature, line 1526-1530); dynamic FIFO allocation per endpoint; non-power-of-2 FIFO sizes;
  Keep-Alive (LS) / (micro)SOFs (HS/FS); hardware bus/packet error handling; some registers implemented in RAM to
  cut gate count; descriptor caching + prefetch; interrupt moderation.
- **§1.2.2 System Bus Interface Features**: AHB or AXI application interfaces (Completer for CSR/RAM-debug
  access, Requester for internal DMA); AXI 3.0-compliant with AXI4-connection caveats (no write interleaving, no
  out-of-order address/data phase); 64/128-bit data, 32/64-bit address; independent Little/Big-Endian per
  Completer/Requester and independent descriptor-vs-data endian selection; up to 32-packet R/W pipelining in
  AXI/Native modes.
- **§1.2.3 USB 3.1 Device Features** (line 1680-1753): up to 16 bidirectional EPs incl. EP0; multiple IN
  transfers in SSP mode; flexible/dynamic-mappable TxFIFOs; simultaneous IN+OUT; 10 Gbps IN + 10 Gbps OUT;
  hardware handles ERDY/burst/all data transfers; multi-transfer setup without host-CPU interrupt-per-transfer;
  stream-based bulk EPs; ISOC EPs with buffer-or-external-FIFO data; dual-power-rail hibernation; External
  Buffer Control (EBC); flexible descriptor (buffer interrupt moderation, multi-transfer, isochronous, control,
  scatter buffering); per-endpoint interrupt-line mapping. Class-specific: UASP stream support; ADC 3.0 support;
  Ethernet-over-USB packet gathering (e.g. multiple 64-byte scattered writes packed into a 1024-byte USB packet
  by hardware); multi-packet interrupt moderation via IOC bit + `DEV_IMOD` timer register; MIPI Gigabit Debug
  support (Appendix F); variable per-endpoint FIFO allocation; isochronous variable-length-per-microframe
  scheduling; clock gating for mobile power.
- **§1.2.4 USB 3.1 xHCI Host Features**: see §2.2 above for the numeric limits; plus "Standard or open-source
  xHCI and class drivers," aggressive power management, memory-access optimization, interrupt moderation,
  descriptor caching, concurrent USB 3.1/2.0/1.1 traffic ("Net bandwidth increased to 19.88 Gbps (2×9.7 Gbps
  USB 3.1 + 480 Mbps USB 2.0)"), Debug Capability (DbC) support.
- **§1.2.5 USB 3.1 DRD Features**: only "Static Device operation" and "Static Host operation" are listed — i.e.
  **no dynamic role-swap feature is claimed in the feature list** (worth flagging: DRD here means
  statically-configured-at-runtime dual capability, not necessarily automatic USB-OTG-style role negotiation —
  and indeed §2.9 explicitly lists **OTG as an unsupported feature**, line 2061).
- **§1.2.6 Power Optimization Features**: 3-tier (System/Architectural, RTL, Gate/physical level) description;
  clock gating between U0→U1/U2/U3; 80-90% of flops made clock-gateable; PHY clock gating during suspend/LPM/
  session-off; CPU clock gating during suspend/session-off; dual-power-rail hierarchy; §1.2.6.2 Hibernation
  detail: PMUs (~5K gates) live on a separate Vaux rail from the ~250K-gate device-mode controller (Vcc);
  "Hibernation feature is supported only in device, host, and DRD configurations" (note callout, line 1926) —
  i.e. presumably not in a Hub/ROUTERIF configuration.
- **§1.2.7 Area Reduction Features**: 2-port RAM (1 read-only + 1 write-only port) instead of true dual-port;
  queues/most-registers in RAM not flops; driver CPU handles rare/non-timing-critical events (Setup decode).
- **§1.2.8 Performance Features**: descriptor caching, packet prefetch, multi-transfer queuing, interrupt
  moderation (Host), packet packing for full bandwidth (Host), concurrent Rx/Tx, concurrent port transfers
  (Host), concurrent USB3.1+USB2.0 transfers (Host).
- **§1.2.9 MIPS Reduction Features**: hardware transfer-level scheduling for periodic+non-periodic (no SW
  intervention mid-transfer); multi-transfer scheduling without extra interrupts; scattered-buffer/scattered-
  packet support; byte-addressing to avoid SW double-copy; "buffer complete" interrupt moderation; hardware-only
  scheduling for high-rate uncompressed video.
- **§1.2.10 Debug Features**: CPU R/W access to all internal RAMs via completer interface; critical state-
  machine states readable via completer interface; FIFO status visible to SW; 64-bit logic-analyzer trace port;
  loopback mode support.
- **§1.3 Area** (Table 1-4, line 2003-2011, baseline gate counts): **Device (4 EPs) ≈ 500 KGates**, **Host
  (1 port) ≈ 1350 KGates**, **DRD (1 port) ≈ 1550 KGates**.

### 2.9 Unsupported Features, Usage Restrictions, and Known Issues (§1.5-1.6, line 2035-2126) — errata-relevant

**Unsupported Configurations** (line 2040-2053): Multi-Port DRD; Single-Port RAM; Number-of-RAMs ≠ 3;
`DWC_USB31_MDWIDTH=32`; Native interface; AHB-as-requester-bus (not recommended — "does not meet USB 3.1
performance requirements... does not support pipelining... not point-to-point"); USB 3.0-only mode; USB 2.0-only
mode; `Number of USB3.1 ESS Root != Number of Enhanced SuperSpeed USB Bus Instances`.

**Unsupported Features** (line 2054-2064): 8-bit/16-bit PIPE data widths (only 32-bit supported); IC-USB;
3-pin/6-pin USB 1.1 serial interface; I2C/CarKit functions; SSIC; **OTG**; ADP; Battery Charger (BC); BIST in
Host Mode.

**Unsupported xHCI Features** (line 2065-2077): Get Port Bandwidth Command (deprecated by spec, implementation
"stays as is" but unsupported — do not use); I/O Virtualization (optional cap); Message Interrupt (optional);
Extended Message Interrupt (optional); Local Memory (optional); Get/Set Extended Properties Commands (optional);
xHCI Audio Sideband (optional).

**Usage Restrictions** (line 2078-2106):
- ADC 3.0 EA feature limited to 8-bit UTMI/ULPI only — do not enable with 16-bit UTMI.
- `host_u3_port_disable[n]` semantics: if asserted for a port number ≥ `host_num_u3_port`, controller assumes no
  PHY attached; on a D3 request it may enter D3 before PHY low-power, increasing PHY static power in D3.
- Do not enable `GUSB3PIECTL[U2P3ok]` and `LLUCTL[U2P3CPMok]` together for P3/P3CPM support in U2.
- Frame-length-adjustment feature is **deprecated in USB 3.1**: `GFLADJ` register power-on value, and
  `fladj_30mhz_reg[5:0]`, `GFLADJ_30MHZ_SDBND_SEL` must be left at default.
- Enable AXI Strict Ordering to avoid a HW/SW race hazard.
- **Ref_clk frequency of 40 MHz is not supported.**

**Known Issues (Databook §1.6, line 2113-2119)**: "Compliance Testing: HW compliance testing is still in
progress at Synopsys Lab, for the status, contact Customer Support." (single item, no other known-issue entries
in Chapter 1 of the Databook itself — the substantive known-issues content is in the Release Notes, §4 below).

### 2.10 Fixed ECNs Appendix (Appendix H, line 21654-21793+) — spec-conformance errata history

The Databook explicitly notes this appendix is "replicated in the programming guide for ease of use" (line
21665). Table H-1 "Fixed USB 3.1 ECNs" tracks each USB-IF/Intel spec erratum/ECN against: affected layer,
"Version of RTL Fixed" (or "N/A" / "Not implemented"), and comments. Selected verification-relevant rows:

- Q1'09 USB 3.1 Errata D.6.301 (Min U1 exit LFPS duration 600ns) — LINK layer — fixed since **1.00a-lca01** —
  "No specific changes were required. controller was following the specification."
- Q1'09 D.6.302 (U1 exit `tNoLFPSResponseTimeout` 2ms) — LINK — fixed 1.00a-lca01 — mark ITP delayed if >32ns
  delay occurs.
- Q1'09 D.6.303 (U1↔U2 transition rule: on remote-initiated exit, always follow the *local* link's current
  U1/U2 timing) — LINK — fixed 1.00a-lca01.
- **ECN009 "efficient ISO/PING"** (Protocol layer) — status **"Not implemented"** — comment: "Targets the host
  scheduler functionality... Currently if there are more than one ISOC endpoint with each endpoint having
  different service intervals, device needs to keep the link in U0 for the endpoint having the largest service
  interval." **This is a real, currently-outstanding functional gap** relevant to power/ISOC verification.
- "US Port state m/c" erratum (Peripheral layer) — status **"Not implemented"** — comment: **"Can workaround by
  enabling GCTL[16]"** — a concrete register-level workaround for a known-outstanding item, directly actionable
  for a verification/debug agent.
- USB 3.1 ECN CTLE (§6.4.4/Table 6-13, "Add CP13 to CP16, polynomial for CP12") — LINK — fixed in **1.10a**.
- USB 3.1 ECN HSEQ (§7.2.1.1.3, "Extends the header sequence number range for Gen2 from 0-7 to 0-15") — LINK —
  fixed in **1.10a**.
- Several Connector/Cable/PHY-layer ECNs are marked "N/A — No changes required" (RTL-independent, mechanical/
  electrical spec changes) — not relevant to functional verification.
- The appendix continues with "Fixed USB 2.0 ECNs" (page 498) and "Fixed xHCI ECNs" (page 509) sub-tables not
  transcribed in full in this pass (line-number citations above cover only the USB 3.1 ECN table actually read).

---

## 3. Install Guide (`DWC_usb31_install.pdf` → converted text) — environment/tool/version prerequisites

### 3.1 System requirements (Table 1-2, install.txt line 314-335)
- OS: **Red Hat Enterprise Linux 5.0/64 or later** with required patches; csh ≥ 6.18.01; make ≥ 3.8.
- Disk: 300 MB (coreConsultant) + 400 MB (DWC_usb31 install) + **14 GB after simulation**.
- Memory: 4 GB swap + 4 GB RAM minimum.

### 3.2 Supported VIP/tool versions for this exact IP version (Table 1-5, install.txt line 612-677)

| Tool | Supported Version |
|---|---|
| coreConsultant | 2023.09 |
| Design Compiler (DC) | 2022.12-SP6 (64-bit only) |
| Fusion Compiler (FC) | 2022.12-SP6 (64-bit only) |
| Formality | 2022.12-SP6 |
| TestMAX ATPG | 2022.12-SP6 |
| Spyglass | 2023.03-SP2 (GuideWare 2023.03 only) |
| PrimeTime | 2022.12-SP5-1 |
| Synplify | 2023.03-SP1 |
| RTL Architect | 2022.12-SP5 |
| VC Static | 2023.03-SP1-1 |
| VC LP | 2023.03-SP1-1 |
| VC SpyGlass | 2023.03-SP2 |
| **VCS Simulator** | **U-2023.03-SP1-1** |
| Verdi | U-2023.03-SP1-1 |
| Python | 3.5.0 |
| Perl | 5.8.3 (Perl DBI needed for SQLite in performance-analysis flow) |
| Discovery VIP | AMBA_SVT U-2023.06, SVT U-2023.03, USB_SVT U-2023.06, MPHY_SVT U-2023.06 |

Notes directly relevant to verification setup:
- "You need a VCS license to run simulations. You can compile and elaborate RTL source code with NCSim and
  ModelSim; **however, Synopsys does not provide compilation, elaboration, or simulation support as a
  deliverable using NCSim and ModelSim**" (footnote a, line 678-680) — matches Release Notes §1.5.2 (below):
  "Only VCS simulator is supported; NCV and ModelSim simulators are not supported."
  - **This is a version-drift point**: earlier Install-Guide revision-history entries (line 149-152, 163) show
    NC-Verilog support was *removed* at some point and Leda RTL checker support was removed too — i.e. simulator
    support has narrowed over the product's history down to VCS-only by 2.10a.
  - "No VHDL simulators are supported, [but] you can generate a VHDL GTECH netlist... for use in your own
    environment" (line 682-683).
  - "Ensure gcc version is compatible between the tool and its platform. For VCS, see Table 5-1 of the VCS
    Release Notes" (line 685-686).
- **AMBA_SVT and USB_SVT must be downloaded/installed separately** from the DWC_usb31 controller image itself
  (only `USB_TS` TestSuite ships packaged with the controller) (line 660-676).

### 3.3 Environment variables (Table 1-6, install.txt line 692-707)
`LM_LICENSE_FILE`, `SNPSLMD_LICENSE_FILE` (license server pointers — must be set **before** running the `.run`
installer, install.txt line 439-441), `LD_LIBRARY_PATH`, and **`DESIGNWARE_HOME`** (base install directory —
"Ensure this directory is writable because... the VIP wrappers are installed in this directory," line 702-706).
`$DESIGNWARE_HOME/bin` must be on `PATH` (line 528).

### 3.4 Customer Verification Environment caveat (§1.6.4.3, line 577-586)
> "The VC VIP library license shipped with DWC_usb31 is intended only to verify the interface level testing of
> the specific IP configuration out-of-the-box in coreConsultant, to confirm that DWC_usb31 meets the
> requirements. The VC VIP library license shipped with DWC_usb31 is **not intended to be used as a full
> featured verification model at the subsystem or SOC level.**"

This is an important scope boundary: the PVE testbench (§1.3 of this report) is unit-level sanity, not a
subsystem/SoC-level verification substitute.

### 3.5 Revision history highlights (install.txt line 109-199) — version-specific document/tool churn
- 2.10a (Jan 2024): added "Receiving IP Updates" chapter.
- 2.00a (Mar 2022): updated Customer Verification Environment, Supported VIP/Tool Versions, env-vars sections;
  updated product-code table and license table.
- 1.80a (Aug 2019): updated license info (Table 1-4).
- 1.30a/1.20a/1.10a-lca02/1.00a-lca01 (no date given, bundled entry): **removed support for Solaris platform,
  Leda RTL checker, and NC-Verilog simulator** — i.e. this is where NCV support was actually dropped, prior to
  the 2.10a text that still footnotes "you *can* compile/elaborate with NCSim... [but] Synopsys does not
  provide support" — meaning even that compile-only allowance is a legacy carve-out, not active support.
- Jan 2017 entry: added minimum csh/make versions, added LPDDR4-QoS-Add-On licensing.
- Aug 2016 entry: "**Removed references to encrypted RTL as it is no longer supported.**"
- May 2016 entry: added a note on `gcc_version` compatibility; **added support for NC-Verilog** (later removed,
  see above — so NCV support was added ~2016 and removed again by some point before 2.10a); removed references
  to Vera and MTI (legacy verification languages/tools).
- Jan 2015: Initial version of this Installation Guide (i.e., the document itself, not the IP, originates here).

---

## 4. Release Notes (`DWC_usb31_relnotes.pdf` → converted text) — v2.10a changelog and known limitations

Single-version document (only 2.10a is covered; no per-prior-version changelog body, though it says historical
STARs are on the SolvNet web portal, not in this document).

### 4.1 Changes from the Last Release — Enhancements and Fixes in 2.10a (relnotes.txt §1.2.1, line 111-178)

This is the direct list of defects fixed going into 2.10a — i.e., **bugs known to exist in the prior release and
now fixed** (useful as "do not assume these behaviors are broken in 2.10a, but they *were* broken in an earlier
version" reference list for anyone validating against an older RTL drop):

- Device: Incorrect Detection of Link Commands during reception of Data Packet Payload.
- coreConsultant Error when selecting more than 4 eSS host root ports (i.e. the 4-port cap was previously also a
  *tooling* bug, not just a spec/RTL limit).
- Functional failure with coreConsultant-based Technology-Specific Cell Binding for CDC Synchronizers.
- USB ISOC data and system interrupt alignment.
- `TxDetectRxLoopback` incorrectly de-asserted when controller is in D3 and PMU is in `ss.Inactive` state and D3
  exit occurs.
- After event-ring-full error, interrupt line failed to assert.
- Lint error causing ISOC PING protocol failure in host mode.
- VTIO Feature Enhancement (see §2.6 cross-reference above re: VTIO not supported/usable in 2.00a).
- Host: PTM (Precision Time Measurement) feature time-adjustment fix.
- Host: Incorrect Detection of Link Commands during reception of Data Packet Payload.
- **Doc: `GDBGLSPMUX.logic_analyzer_trace` default value incorrect in Programming Guide** — a documentation
  errata fix, i.e. earlier Programming Guide revisions had a wrong default value documented for that register
  field.
- Wrong clock used for `usb4_usbcmd_run_stop` generation.
- Device: USB2 link fails to respond correctly to USB reset if it enters D3 with link in L1 state.
- ISOC pipelined TP.ACK getting ZLP response after burst is stopped.
- Link Registers incorrectly saved after save/restore error.
- Host: Programming `USBCMD.HCRST` might not translate to a warm reset in the absence of far-end receiver
  termination.
- Host: Overcurrent during D3 abruptly terminates ongoing PHY activity.
- Controller's link may take longer than expected to complete P3/P3CPM/P4→P2 transition.
- Controller incorrectly drives `pipe4_pclk_rate` during D3 entry.
- **Doc: "DWC_usb31 controller supports only 32-bit mode of operation on USB3 PIPE Interface"** — another
  documentation-only fix confirming the 32-bit-PIPE-only restriction (cross-references §2.9's Unsupported
  Features entry, which is the functional statement of the same restriction).
- Device: De-assert `Txvalid` upon detecting `Txready` when soft-disconnect is programmed during Remote
  Wakeup/Chirp signaling.
- Host: Terminate Resume if `HostDisconnect` is asserted.
- Host: Detect FS/LS device disconnection using `utmi_hostdisconnect` signal.
- Clock Module Enhancements; legacy external-clock-gating slow-exit causing TBR overflow.
- AXI CSR burst write with `WSTRB=0` support (added).
- Device: Handling non-control EP receiving a DP with setup-bit enabled, or a TP with status type.
- Device: `RXSTS` for ISOC Deferred DPH is missed.
- Incorrect power-state transition during D3 exit while in U3 link state.
- Unexpected PIPE power-down signal transition P3→P3CPM upon D3 entry on a disabled port.
- Host controller timeout due to packet-counter overflow while parsing cached TRBs.

### 4.2 Known Issues and Limitations (relnotes.txt §1.5, line 213-289) — the direct errata list for THIS version

**§1.5.1 Feature Limitations**: delegates entirely to the Databook's "Unsupported Features and Usage
Restrictions" (§2.9 of this report) — release notes add no separate feature-limitation list of their own.

**§1.5.2 Known Simulation Environment Problems** (line 222-242) — directly actionable for a verification agent
setting up or debugging the PVE:
- **Only VCS simulator is supported; NCV and ModelSim are not supported.**
- **Gate-level simulation is not validated.**
- "Even though the PVE is tested for multiple configurations, it is not tested for all random parameter
  permutations/combinations." (contact Support if a specific config fails)
- **BIST loopback test may fail depending on configuration** — root cause given: "the test uses the RAL model
  for monitoring the `BBISTCTRL` register values. However, this will not be an issue if the `BBISTCTRL` register
  values are monitored through the AXI Completer interface" — i.e. a known RAL-vs-real-interface monitoring
  mismatch, "will be fixed in the next release" (still open as of 2.10a).
- **Multi-port and Router configurations do not support eusb2 tests** (explains the separate EUSB2 PVE
  sub-testbench scope noted in §1.3 above).
- VC Spyglass CDC/RDC flow "is only tested for a few configurations" — contact Support for others.
- **PVE simulation with `DWC_USB31_PCLK_AS_PHY_INPUT` configuration is not supported in router-enabled
  configurations (`DWC_USB31_EN_ROUTERIF=1`)** — a concrete parameter-combination-level simulation gap.
- In coreConsultant GUI Simulator Setup, **the "Enable TCM" option must not be enabled.**
- Two named tests may fail with certain configurations due to a PHY issue:
  `router_if_host_usb_20_na_31_ssp_pipe4_xfer_pm_sus_res_xfer` and
  `router_if_host_usb_20_na_30_ss_pipe4_xfer_pm_sus_res_xfer`.

**§1.5.3 Known Synthesis and Formality Problems** (line 244-284):
- Scan coverage 99.7%, with several *expected* (documented, not-a-bug) scan violations: TEST-126 (clock-gating/
  clock-mux latches not scannable — expected); D14/C6 (negedge flops in clock-gating and suspend/resume
  save-restore logic — expected, mitigated by using scan clocks `{45 55}` instead of `{55 45}`); TEST-504/
  TEST-505 (clock-mux latch always-0/always-1 in scan mode — expected); C17/C18 (generated clock routed to
  `ram_clk_out` and to the `logic_analyzer_trace` output port — expected).
- coreConsultant GUI **does not support** an FPGA synthesis run targeting Synplify.
- Formality for Host mode needs **100 GB swap for a 1-port config, 256 GB swap for a 4-port config** — a
  concrete, version-specific resource-planning number.
- **DC Autoread mode is not supported.**

### 4.3 Quality Metrics (§1.4, line 204-206)
"Both Host controller and Device controller are USB-IF certified." (No further quantitative quality-metrics
detail is given in this document beyond that one sentence.)

---

## 5. Link-block register/CSR extract (`link_block_extract.txt`)

This file is a bitfield-level extract (author unknown/pre-existing in the repo) of the USB 3.1 **Link-layer CSR
block**, apparently pulled from the Programming Guide's register-map chapter (its own headers cite source line
numbers 20573–24000 into that other document, not re-verified in this pass). It enumerates, register by register:
bit range, field name, R/W, description, and (mostly redacted/computed) "Value After Reset" shown as the
literal placeholder text `=mpformat "0x%x"` plus a numeric "Reset Mask".

Registers covered, in order: `LU1LFPSRXTIM`, `LU1LFPSTXTIM`, `LU2LFPSRXTIM`, `LU2LFPSTXTIM`, `LU3LFPSRXTIM`,
`LU3LFPSTXTIM`, `LPINGLFPSTIM`, `LPOLLLFPSTXTIM`, `LSKIPFREQ`, `LLUCTL`, `LPTMDPDELAY`, `LSCDTIM1..4`,
`LLPBMTIM1/2`, `LLPBMTXTIM`, `LLINKERRINJ`, `LLINKERRINJEN`, `GDBGLTSSM`, `GDBGLNMCC`, `LLINKDBGCTRL`,
`LLINKDBGCNTTRIG`, `LCSR_TX_DEEMPH[_1/_2/_3]`, `LCSRPTMDEBUG1/2`, `LPTMDPDELAY2`.

**Cross-reference to the Databook (§2 above)**: the "Value After Reset" placeholders in this extract are exactly
the coreConsultant-computed **Register Power-On Value Parameters** documented in Databook §4.8 (line 7339
onward, only partially transcribed in this pass — direct hits confirmed: `DWC_USB31_LINK_U1_LFPS_RX_TIMER_INIT`
(line 8302), `DWC_USB31_LINK_U1_LFPS_TX_TIMER_INIT` (line 8323), `DWC_USB31_LINK_U2_LFPS_RX_TIMER_INIT` (8354),
`DWC_USB31_LINK_U2_LFPS_TX_TIMER_INIT` (8368), `DWC_USB31_LINK_U3_LFPS_RX_TIMER_INIT` (8398),
`DWC_USB31_LINK_U3_LFPS_TX_TIMER_INIT` (8415), `DWC_USB31_LINK_PING_LFPS_TX_TIMER_INIT` (8438),
`DWC_USB31_LINK_POLL_LFPS_TX_TIMER_INIT` (8450), `DWC_USB31_LINK_SKIP_FREQUENCY_INIT` (8485),
`DWC_USB31_LINK_LUCTL_INIT` (8567), `DWC_USB31_LINK_PTM_DATAPATH_DELAY_INIT`/`_DELAY2_INIT` (8582/8594),
`DWC_USB31_LINK_SCD_TIMER1..4_INIT` (8619-8671), `DWC_USB31_LINK_LPBM_TIMER1/2_INIT` + `_TX_TIMER_INIT`
(8697-8738), `DWC_USB31_LINK_DEBUG_CONTROL_INIT` (8745), `DWC_USB31_LINK_DEBUG_CNT_TRIGGER_INIT` (8752). This
confirms: **every LFPS/LPBM/SCD/PTM link-timing register's power-on value is a Basic/Advanced-config-time
parameter**, i.e. these are not truly hardwired reset values — they are software/synthesis-time-programmable
defaults exposed through coreConsultant, and later re-programmable via CSR writes at runtime (per Databook line
4812-4821: "All global and link registers can be programmed by software later, but it is recommended to
configure the power-on initialization... before synthesis"). A verification agent building a register model
(RAL) or checking reset values must pull the *actual* numeric reset value from the specific coreConsultant
configuration report/`DWC_usb31_params.v`, not assume a single fixed hex constant — the value is
configuration-dependent.

Functionally notable fields from this extract for a Link-layer verification agent:
- `LLUCTL` bit 28 `support_p4` / bit 29 `support_p4_pg`: gates PHY P3.CPM/P4 support — corresponds directly to
  Databook parameter `DWC_USB31_SSPHY_SUPPORT_P3CPM_P4` (§2.5-adjacent, databook line 5537): "To enable P3.CPM
  and P4, enable this parameter **and program LUCTL[28]=1**" — i.e. the parameter alone is not sufficient at
  runtime; the CSR bit must also be set. This is a two-part (config-time + runtime-CSR) enable that a testbench
  must model correctly.
- `LLUCTL` bit 12 `U2P3CPMok`: directly the register referenced in Databook Usage Restriction "Do not enable
  GUSB3PIECTL[U2P3ok] and LLUCTL[U2P3CPMok] for supporting P3/P3CPM in U2" (§2.9 above) — i.e. this extract
  identifies the exact bit position (`LLUCTL[12]`) for that restriction.
- `LLUCTL` bit 10 `force_gen1`: software override to force Gen1 (5 Gbps) link operation regardless of
  negotiated capability — directly testable knob for speed-degradation verification.
- `LLINKERRINJ` / `LLINKERRINJEN`: a full TX/RX error-injection register pair (corrupt TS1/TS2/TSEQ, CRC5/16/32,
  framing symbols, LFPS, deferred/delayed insertion, back-to-back error count threshold) — this is the
  link-layer error-injection mechanism a negative-test/robustness verification plan would target.
- `GDBGLTSSM` / `GDBGLNMCC`: LTSSM and Link-Number/Max-Capability-Count debug-observation registers (reset
  values largely redacted in this extract, but presence + field count confirm these are readable-state debug
  registers per the Debug Features feature-list entry, §2.8 above: "critical state machines' states read through
  completer interface").

---

## 6. Summary of cross-document contradictions/refinements found

1. **USB2-only / USB3.0-only mode**: Databook Chapter 4 parameter formulas (`EN_USB2_ONLY`, `EN_USB30_ONLY`)
   are written as if these modes are selectable, but Databook §1.5 explicitly lists both as **Unsupported
   Configurations** in this release. Treat the formulas as latent/legacy generality, not a supported target.
2. **`DWC_USB31_MDWIDTH=32`**: offered as a Values-list entry ("Reserved-1 (32)") in §4.4's parameter table, but
   separately declared unsupported in §1.5. The parameter table's own "Reserved-1" labeling actually already
   signals this — the two sources agree once you notice the label.
3. **Multi-Port DRD**: absent from the Product Codes catalog (only DRD-**Single**-Port exists) *and* explicitly
   named in Unsupported Configurations — two independent sections of the same document corroborate each other.
4. **PIPE data width = 32-bit only**: stated three independent ways across three documents — Databook Unsupported
   Features list (§1.5), Databook feature narrative, and as a *documentation correction* in the Release Notes
   2.10a changelog ("Doc: DWC_usb31 controller supports only 32-bit mode of operation on USB3 PIPE Interface") —
   i.e. earlier doc revisions apparently mis-stated this, and 2.10a is the fix.
5. **VTIO maturity**: Databook lists VTIO as a Host-Config "Premium New Feature (EA)"; Release Notes record that
   VTIO "not supported and should not be enabled in DWC_usb31 2.00a" and that 2.10a shipped a "VTIO Feature
   Enhancement" — so VTIO's usability is version-gated even within the Premium/EA feature itself.
6. **Simulator support narrowed over time**: Install Guide revision history shows NC-Verilog was added (~May
   2016) then later removed (bundled 1.00a-lca01–1.30a entry), Leda and Solaris support removed at the same
   point, and by 2.10a only VCS is a supported simulator (Release Notes §1.5.2 confirms) — ModelSim/NCSim are
   compile-only-at-best, unsupported for simulation.
7. **`LLUCTL[28]` two-part enable**: the Databook's parameter description for `DWC_USB31_SSPHY_SUPPORT_P3CPM_P4`
   and the `link_block_extract.txt` register bitfield for `LLUCTL.support_p4` are two views of the same
   config-time+runtime-CSR gate — neither source alone tells the full story (config parameter enables the
   *capability*; the CSR bit at runtime actually turns it on).
8. **Top-level `DWC_usb31_databook_WM-25380.pdf` vs `IP\DWC_usb31_databook.pdf/.txt`**: the top-level file is a
   password-encrypted, presumably watermarked copy of the same Databook; it could not be opened, and all
   Databook content in this report instead comes from the unencrypted copy in `IP\`. If per-user watermark
   provenance ever matters, that gap should be revisited with the correct password/PID.
