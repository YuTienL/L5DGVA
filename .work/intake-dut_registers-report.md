# DUT / DUT Registers — Deep Extraction (Category 4)

Source root: `D:\DV\Task\USB\DOC\`. This report is a queryable digest of the *primary
register-map documents* for the PAISB SoC's USB subsystem and its neighboring SS_QDMA
(Command-Queue/DMA) subsystem — not an index. Every fact below was read out of the actual
document text (converted via `antiword`/`pandoc`/`openpyxl`/`xlrd` for this extraction; no
value was invented or recalled from general USB3/DWC_usb31 knowledge unless the source text
said so explicitly).

Conversions used (kept in scratchpad, not part of the deliverable):
`C:\Users\peter.lin\AppData\Local\Temp\claude\D--DV-Task-DV-Agent-Harness-L5\278c9eb4-a877-4a03-af82-5a5f90fa4e62\scratchpad\extract\*.txt`

---

## 0. Headline cross-reference finding: the SoC address-map formula

Three *independent* documents, read separately, triangulate into one consistent 32-bit
address-map rule for this SoC. This is the single most load-bearing fact in this whole
extraction set because it lets you convert any "local" register-table address in any of
these docs into the real system address the VIP/testbench must drive.

**Rule, derived and verified against three sources:**

```
system_address = 0x1000_0000  |  local28
```
where `local28` is the 28-bit "Address[27:0]" value the CQ document uses for its top-level
map, split as: bits[27:24] select a subsystem directly for most values, except when
bits[27:24]=0, in which case bits[23:20] sub-select among Global/CQ/CPU-SS/QDMA-SS/SE.

| Evidence | Source | Fact |
|---|---|---|
| 1 | `PAISB_Global_Reg_260731.doc` (antiword ln 1-4, "Register base definition" table) | "Global Register base 0x1000_0000 — Base of system address to all global registers." → local `0x0000000` = system `0x1000_0000`. ✓ matches rule. |
| 2 | `SS_QDMA\PAISB_CQ_Reg_260810.docx` (top-of-doc "Address Map" table, ln 22-56 of converted txt) | 28-bit nibble table: `0x00XXXXX`=Global, `0x01XXXXX`=CQ, `0x02XXXXX`=CPU SS, `0x03XXXXX`=QDMA SS, `0x04XXXXX`=SE, `0x05-0FXXXXX`=Reserved, `0x1XXXXXX`=Reserved, **`0x2XXXXXX`=Video Out subsystem registers**, `0x3XXXXXX`=Reserved, `0x4XXXXXX`=Vision SS, `0x5XXXXXX`=Vision SS(FRONT), `0x6XXXXXX`=General Connectivity SS, `0x7XXXXXX`=Reserved, `0x8XXXXXX`=Memory Controller, `0x9-FXXXXXX`=Reserved. |
| 3 | `SS_QDMA\PAISB_SS_QDMA_Reg_260605.docx` §1 (ln 5) | "SS_QDMA sub-system control registers start at base address **0x1030_0000**... the CQ at **0x1010_0000** and the DMA at **0x1031_0000** onward." local `0x0100000`→system `0x1010_0000` ✓; local `0x0300000`→system `0x1030_0000` ✓; local `0x0310000`→system `0x1031_0000` ✓. |
| 4 | `register__ssvout_0806.xlsx` sheet `ss_vout_reg00` header row | `Base Address = 0x12000000`. Rule predicts Video-Out-SS window = local `0x2000000` → system `0x1200_0000`. **Exact match.** |
| 5 | `USB_Reg_260727.docx` (ln 16-32) | "usbtop\[0\]" register blocks live at `0x1270_0000`–`0x1273_FFFF`, which fall *inside* the `0x1200_0000`–`0x12FF_FFFF` Video-Out-SS window from evidence 2+4. So **the USB controller instance(s) are a sub-region of the "Video Out subsystem"** address space, at offset `+0x0070_0000` from the SS_VOUT base. |

**Implication for anyone building an address map for the USB VIP/DUT bring-up:** the DWC_usb31
controller CSR window (`0x1271_0000`–`0x1271_FFFF`, see §2 below) sits at system address
`0x1271_0000`, and everything else in `USB_Reg_260727.docx` (`usbtop external register`
blocks) sits at `0x1270_0000`–`0x1273_FFFF`. All of it is a sub-window inside the 16MB
`0x1200_0000`–`0x12FF_FFFF` "Video Out subsystem" range that `PAISB_CQ_Reg_260810.docx`'s
top-level map and `register__ssvout_0806.xlsx`'s own declared base agree on.

**Also confirms subsystem naming**: `PAISB_Global_Reg_260731.doc` calls this same subsystem
`swrst_ss_vout` = "**VideoOut Sub-system**" (ln 356-359) and its `clken_ss_vout` bit-map (ln
464-479) lists `[01]: usbrefclk (PHY)` and `[10]: usblclk` as two of its member clocks —
alongside `pcierefclk`, `macclk0/1` (Ethernet), and `mtxdispclk/mtxdsiclk` (MIPI display).
`register__ssvout_0806.xlsx` sheet `ss_vout_reg00` independently confirms this: its top
interrupt-aggregator / CQ-interrupt-select register (`cqint00en` at offset `0x0050~1`, RW,
default `0x0`) has explicit bit assignments `[9]: usb0 int` and `[10]: usb1 int` alongside
`[8]: pcie int`, `[4]/[5]: mac0/mac1 int`, `[11]: mipitx int` (ln 57-67). And its clock/reset
control block (`ss_vout_reg00`, offsets `0x0080`–`0x0098`) has explicit per-block bits:
`mswrst[3]=usb0, [4]=usb1` (ln 87-88), and separate `usb0_clken` at `0x0097` / `usb1_clken`
at `0x0098` (ln 100-101, both RW, `2:0`, default `0x7`). So the SoC's naming for "the two USB
ports" at this integration layer is **usb0 / usb1**, which is the same pairing `USB_Reg_260727.docx`
calls **usbtop[0] / usbtop[1]**.

So the picture the four documents jointly paint is:
`SS_VOUT` (0x1200_0000, 16MB) → contains `usb0`/`usb1` sub-modules (bus-matrix "device" entries,
clock/reset/interrupt-aggregate bits) → each of which is (per `USB_Reg_260727.docx`) an
"usbtop[N]" instance exposing regclk/axiclk/controller/sram/usb3phy/usb2phy/apb-parity pages
at `0x1270_0000`-`0x1273_FFFF` **and a DWC_usb31 controller CSR block at `0x1271_0000`-`0x1271_FFFF`.**

---

## 1. `PAISB_Global_Reg_260731.doc` — SoC-wide global control/clock/reset registers

**What it is**: chip-level (not USB-specific) global register document. Version 0.1,
"Preliminary", dated April 23 2026 (note: filename says `260731` = Jul 31 2026 but the doc's own
printed date is April 23 2026 — the file was evidently saved/renamed later without updating
its internal cover date; worth flagging if anyone cites "the July 31 doc" expecting July
content).

**Where it lives**: `D:\DV\Task\USB\DOC\PAISB_Global_Reg_260731.doc`

**Base**: `0x1000_0000` (stated explicitly, "Register base definition" table, converted ln 1-4).

**Register page map** (ln 6-33): `0x00_0000~00FF`=Interrupt/CQ-event, `0x00_0100~01FF`=IO-Trap/Suspend/Isolation,
`0x00_0200~03FF`=RESET, `0x00_0300~03FF`=CLKEN, `0x00_0400~05FF`=CLKSRC, `0x00_0600~07FF`=CLKPHASE,
`0x00_0800~0BFF`=CLKDIV, `0x01_0000~01FF`=Chip-ID+PinMux, `0x01_0100~01FF`=PGPIO, `0x01_0200~02FF`=FMGPIO,
`0x01_0300~03FF`=EGPIO, `0x01_0400~04FF`=TGGPIO, `0x02_0000~00FF`=SW-REG+Probe+DateCode,
`0x02_0100~03FF`=TOKEN, `0x03_0000~05FF`=PLL0-3, `0x03_0600~06FF`=PVT-external, `0x01_0700~07FF`=XTAL/XPRSTN
(typo in source: prefix should probably be `0x03_07xx`, printed as `0x01_0700`), `0x08_0000~00FF`=PVT-internal.

**Access-type legend given by the doc itself** (ln 46-52): `rw`=read/write, `wc`=write-1-clear,
`rws`=read/write + write-1-set, `rwc`=read/write-1-clear, `rwd`=read/write double-buffered,
`rd`=read-only double-buffered, `r`=read-only. This is the canonical legend for all PAISB reg
docs family-wide — every other doc in this set uses the same convention.

**Key registers extracted verbatim (address / bit / attr / name / reset / meaning):**

| Addr | Bit | Attr | Name | Reset | Meaning |
|---|---|---|---|---|---|
| 0x00_0000~1 | [0] | r | gpiointevt | 0x0 | All-GPIO interrupt status |
| " | [2] | rwc | uirsmintevt | | UI resume interrupt status, W1C |
| " | [6] | rwc | apbtz_err_intevt | | Global APB trust-zone error event |
| " | [7] | rwc | apbchk_err_intevt | | Global APB parity-check error event |
| 0x00_0200 | [0] | w | swrstall | 0x0 | Software reset ALL modules |
| 0x00_0201 | [0] | rw | cqrsten | 0x0 | 1=CQ resets when WDT resets CPU engine |
| 0x00_0250/0x58 | [0] | rws/wc | swrst_set/clr_ss_vout | 0x0 | Software reset to **VideoOut Sub-system** (this is the USB block's chip-level soft reset) |
| 0x00_0270/0x78 | [0] | rws/wc | swrst_set/clr_ss_qdma | 0x0 | Software reset to **Compute Sub-system** (contains CQ+DMA); comment: "*Keep 3 APB clocks and auto-recover to 0 to avoid CQ APB dead-lock*" — an explicit erratum/caution about this reset bit |
| 0x00_0350~1 | [15:0] | rws | clken_set_ss_vout | 0x0000 | Clock-enable set for VideoOut/USB domain. Bit map: `[00]pcierefclk(PHY) [01]usbrefclk(PHY) [02]mtxrefclk(PHY) [03]macptpclk [04]macclk0 [05]macclk1 [06]macaclk [08]pciefwclk [10]usblclk [12]mtxscclk [13]mtxdispclk [14]mtxdsiclk` |
| 0x00_0358~9 | | wc | clken_clr_ss_vout | NA | Clear-side of the above |
| 0x00_0400 | [2:0] | rw | seclksel | 0x0 | SE clock source select: 0-3=SPLL0-3, 6=XTALSRCCLK, 7=XTAL |
| 0x00_0483 (ln 783) | [2:0] | rw | usbrefclksrc | 0x0 | **usbrefclk clock source selection** |
| 0x00_0Axx (ln 846) | [2:0] | rw | usblclksrcs | 0x6 | **usblclk clock source selection** |
| 0x00_0A?? (ln 1169) | [7:0] | rw | usbrefclkdiv | 0xF | "usbrefclk = usbrefclksrc / (usbrefclkdiv+1)" |
| 0x00_0A?? (ln 1197) | [7:0] | rw | usblclkdiv | 0x0 | "usblclk = usblclksrc / (usblclkdiv+1)" |
| 0x02_0205 (ln 1590) | [15:0] | rw | token_ss_vout | -1 (all 1s) | Security token for VideoOut(USB) subsystem |
| 0x02_0207 (ln 1596) | [7:0] | rw | token_ss_qdma | -1 | Security token for QDMA subsystem |
| 0x02_0221x (ln 1670-1672) | [31:0] | rwc/rw | ssvout_esmerr/esmen | 0 | ESM (error-safety-monitor) interrupt event/enable for SS_VOUT (USB) |
| 0x02_0221x (ln 1678-1680) | [31:0] | rwc/rw | ssqdma_esmerr/esmen | 0 | ESM interrupt event/enable for SS_QDMA |

**Isolation registers** (ln 281-306): `isoen_ss_vout` (0x00_0184, [0]) and `isoen_ss_qdma`
(0x00_0186, [3:0], bit0=NPU bit1=VPU) are the power-domain isolation-enable bits for these two
subsystems — relevant for any power-aware USB reset/wake sequence checking.

**Cross-reference / contradiction check**: this document never once mentions a byte address in
the `0x1270_xxxx`/`0x1200_xxxx` range (grepped explicitly, zero hits) — it only ever talks about
the USB/VideoOut domain through bit-indexed handles (`swrst_set_ss_vout[0]`, `clken_set_ss_vout[1]`,
`token_ss_vout`, `ssvout_esmerr`). It is **not** a source of the USB block's byte-level base
address; that only comes from `USB_Reg_260727.docx` / `register__ssvout_0806.xlsx` /
`PAISB_CQ_Reg_260810.docx`'s address map, cross-referenced in §0 above.

---

## 2. `USB_Reg_260727.docx` — SoC-wrapper ("usbtop") register map around DWC_usb31

**What it is**: the SoC-integration-level "usbtop external register" document — i.e. the glue
registers PAISB added around the licensed DWC_usb31 controller IP and its two PHYs (USB3
SuperSpeed PHY + USB2 femtoPHY). It is explicitly **not** a register-level description of the
DWC_usb31 controller itself (see the critical gap noted below).

**Where it lives**: `D:\DV\Task\USB\DOC\USB_Reg_260727.docx`. Cover: "Preliminary", **JUN. 08,
2026**, Version 0.0 (again note: filename date 260727 = Jul 27, but printed cover date is Jun 8 —
same stale-cover-date pattern as the Global doc).

**Top-level layout** (ln 11-51 of converted txt) — TWO USB instances, each with an *identical*
byte-offset map:

```
usbtop[0]                                  usbtop[1]
0x1270_0000-0FFF  regclk                   0x1270_0000-0FFF  regclk
0x1270_1000-1FFF  axiclk                   0x1270_1000-1FFF  axiclk
0x1270_2000-2FFF  controller               0x1270_2000-2FFF  controller
0x1270_3000-3FFF  sram ctrl                0x1270_3000-3FFF  sram ctrl
0x1270_4000-4FFF  usb3phy                  0x1270_4000-4FFF  usb3phy
0x1270_5000-5FFF  usb2phy                  0x1270_5000-5FFF  usb2phy
0x1271_0000-FFFF  DWC_usb31 controller reg 0x1271_0000-FFFF  DWC_usb31 controller reg
0x1272_0000-FFFF  USB3PHY tca register     0x1272_0000-FFFF  USB3PHY tca register
0x1273_0000-FFFF  USB3PHY CR register      0x1273_0000-FFFF  USB3PHY CR register
```

**⚠ DUT-007 (disputed port-1 base) — direct evidence from this document**: the table for
`usbtop[1]` (ln 34-51) is **byte-for-byte identical** to `usbtop[0]`'s (ln 16-32) — same
`0x1270_0000`–`0x1273_FFFF` range repeated verbatim. The document gives **no distinct absolute
address for instance 1**. Two explanations are consistent with everything else read in this
extraction pass:
  (a) it is a template/copy-paste artifact (author reused instance-0's table as a stand-in,
      intending "the same relative layout applies per-instance, offset by an as-yet-undocumented
      per-instance base"), or
  (b) it is a genuine documentation gap and the actual second-instance decode address must come
      from RTL (address-decoder parameters) or a system-level address-map spreadsheet that is
      **not present anywhere in this document set.**
  Ruling out option "same physical address, selected another way" is possible: §0 above shows
  the whole SS_VOUT window is 16MB (`0x1200_0000`-`0x12FF_FFFF`) while usbtop[0] only occupies
  16KB of it (`0x1270_0000`-`0x1273_FFFF`), so there is ample undocumented address space (e.g.
  `0x1274_0000`+) for a second, distinctly-based instance — the map doc simply never states it.
  **Conclusion for DV/VIP purposes: treat port-1's base as UNRESOLVED/NOT SOURCED from this
  document set; do not assume it equals `0x1270_0000` in the live system, and do not assume a
  specific alternate offset without an RTL/address-map citation.**

**⚠ Second critical gap found by cross-reference**: The "DWC_usb31 controller register" block
(ln 1788-1796) is documented only as a pointer:
> "0x1271_0000~0x1271_FFFF — IP Control register (reference to
> `\\ichsfs01\IC_Project\PAISB\IP_Digital\Synopsys\DWC_usb31\pull_down_ver\DWC_usb31_programming.pdf` CH1)"

This means **GCTL, DALEPENA, DCTL, DCFG, DSTS, GEVNTCOUNT, GSTS — every core DWC_usb31 register
this session's live build has touched or disputed — are NOT itemized in any of the four
documents in the assigned "real material" list.** They live entirely inside
`DWC_usb31_programming.pdf`, which is **not present anywhere under `D:\DV\Task\USB\DOC\` or its
subfolders** (only `DWC_usb31_databook_WM-25380.pdf` is present at the top level, and that is a
*different* document — the databook, not the programming guide — and it is additionally
**password-protected against text extraction** — `pdftotext` on it returns "Incorrect password").
Same story for the two PHY register blocks: `0x1272_0000` (tca) and `0x1273_0000` (CR) are both
pointer-only entries citing `dwc_usbc31sspphy_tsmc12ffcns_databook.pdf` (chapters 14 and 13
respectively) at a `\\ichsfs01\...` network path — also not present in the provided material.
**Net effect: none of GCTL/DCTL/DCFG/DSTS/GEVNTCOUNT/GSTS/DALEPENA's addresses, bit-ranges,
reset values, or access types can be sourced from the doc/excel material assigned to this
category.** Any register-level claim about those core registers must be cited from
`DWC_usb31_databook_WM-25380.pdf` or `DWC_usb31_programming.pdf` directly (the databook is
present but locked; the programming guide is entirely absent) — flag this explicitly whenever
GCTL/DCTL/etc. come up in DUT/VIP work, per CLAUDE.md's citation requirement.

**⚠ DUT-003 (usbswrst @ 0x0034) — now independently confirmed by this document.** Exact register
found (ln 168, `usbtop external register: regclk` table):

```
Address: 0x1270_0034~0035   Bit: 15:0   Attr: RW   Name: usbswrst   Reset: 16'h0
Description: "USB top software reset. Write 1 to activate reset. Write 0 to deactivate."
  [0] cr_para_clk   [1] pclk   [2] aclk   [3] rupz   [4] wupz
  [5] ram0clk  [6] ram1clk  [7] ram2clk  [8] phyramclk  [9] ctrl
```
This is a **per-domain, per-clock software-reset register** — 10 individually addressable
bit-fields, each gating reset of one clock domain of the usbtop wrapper (not a single
whole-block reset bit). Offset `0x0034` relative to the `regclk` page base (`0x1270_0000`), so
absolute address `0x1270_0034`, 16-bit register spanning bytes `0x0034`-`0x0035`. This matches
and refines DUT-003's "usbswrst at 0x0034" resolution: it is real, RW, 16 bits wide, default 0,
and every individual bit gates a distinct internal clock/reset domain rather than being a
monolithic reset.

**Full register-page inventory (6 pages fully read, ~230 discrete register rows total)**:

- **`regclk` page** (`0x1270_0000`-`0x00FF`, ln 53-215): interrupt status/enable
  (`usbintsts`/`usbinten`, 24-bit, bits [19:0]=DWC_usb31 core int, [20]=pslverr_usb31,
  [21]=reg-guard, [22]=tca_int, [23]=apb_s_pty_err), 16× `cqNintsel` (CQ event-select, 5-bit,
  default `5'h1F`), clock-enable/phase/div controls (`pipeclken`/`utmiclken`/`phyclksel`/`ramclksel`
  at `0x0030`; `pipeclk_phase`/`utmiclk_phase` at `0x0031`/`0x0032`; `paraclkdiv` at `0x0033`;
  **`usbswrst` at `0x0034`** — see above), probe/debug (`prbsel`, `prb_wups`, `prb_rups`,
  `probe_usb`), date-code (`MON/DAT/HOU/MIN` at `0x00FC`-`0x00FF`).
- **`axiclk` page** (`0x1270_0100`-`0x01FF`, ln 217-298): AXI user-signal config (`usb_m_aruser`/
  `usb_m_awuser`, 9-bit, TZC400 ID + 16-ring-buffer-select + bypass/ring-buffer-mode bit),
  QoS (`arqos_s_ups`/`awqos_s_ups`), low-power handshake (`csysack_s/m`, `cactive_s/m`), and an
  AXI up-sizer block (`rupsbusy/err`, `wupsbusy/err`, `wupsen/wupslasten/wupsearlyen/wups4ken`,
  `rupsen/rupsreorderen/rupsearlyen/rups4ken`).
- **`controller` page** (`0x1270_0200`-`0x0231`, ln 300-397): logic-analyzer trace ports,
  `pme_en`, Synopsys "STAR fix" disable-control register (`star_fix_disable_ctl_inp`, 32-bit),
  `bus_filter_bypass` (default `4'h3`), `fladj_30mhz_reg` (HS jitter correction, default `6'h20`),
  **`devspd_ovrd`** at `0x1270_022A` (4-bit, default 0) — "Option to Over-ride the device
  speed(**DCFG.DEVSPD**) through external Top level I/O's of the controller" — this is the
  **only place in the entire document set that even names a DWC_usb31 core register field**
  (`DCFG.DEVSPD`), confirming DCFG exists in the core and is normally driven internally, with
  this wrapper bit providing an external override path — but the field's own address/bit-range
  is not given here (see the DCFG gap above); also `startrxdetu3rxdet`, `ltssm_clk_state`,
  `pme_generation`, `pipe_phy_mode`/`pipe_compliance`/`pipe_txmargin`/`pipe_txswing`,
  `pipe4_pclk_rate`/`pipe4_rxstandby`/`pipe4_rxstandbystatus`.
- **`sram ctrl` page** (`0x1270_0300`-`0x0367`, ln 399-469): `sramsd`/`sramds`/`sramslp` (6-bit
  shutdown/deep-sleep/light-sleep enables, one bit per macro: DESC/TXFIFO/RXFIFO/UPHY/WUPZ/RUPZ
  RAM), `pudelay`, SRAM BIST (`bistmode`/`bistfinish`/`bistfail`/`errmap`), gated-clock disables
  (`disreggatedclk` default `1'h1`, `disgatedsmcken` default `1'h1`), and per-bank column-repair
  fields (`ram1_redenio`/`ram1_fadio`, `rupz_redenio`/`rupz_fadio`) with correct/can-fix/reden-address
  status registers.
- **`usb3phy` page** (`0x1270_0400`+, ln 471-1107, ~230 fields — largest page): `u3phyrst`
  (default `1'h1`, active reset held by default), `u3phy_opmode`, an extensive DWC USB3.1 SS PHY
  raw-PCS control surface matching the PHY databook's signal names 1:1 — `phy0_cr_para_sel`
  (JTAG-vs-CR-interface select), `upcs_pipe_config`, `ext_pclk_req`, SRAM
  bypass/init/load-done handshake, power-gating handshake (`pg_mode_en`, `upcs_pwr_stable`,
  `phy0_ana_pwr_en/stable`, `phy0_pcs_pwr_en/stable`, `phy0_pma_pwr_en`), MPLLA/MPLLB full
  control set (force-enable, SSC-enable, div/multiplier/bandwidth/fracn-ctrl/ssc-freq-cnt
  init+peak/clk-sel/range/tx-clk-div — dozens of fields, defaults mostly non-zero e.g.
  `phy_ext_mplla_multiplier`=`8'h7D`, `phy_ext_mplla_bandwidth`=`16'h2F`), reference-clock
  divider/range select (`phy_ext_ref_range`, 3-bit code table 19.2MHz-200MHz), RX
  adaptation/DFE enables, resistor-tune handshake, boundary-scan controls.
- **`usb2phy` page** (`0x1270_0500`+, ln 1109-1742): standard **UTMI+**-level femtoPHY control
  surface (matches `UTMI-PLUS-SPECIFICATION.pdf` naming) — `u2phyrst`, `atereset`, `fsel`
  (ref-clock-freq select, default `3'h1`=20MHz), `refclksel` (default `2'h2`), `commononn`,
  `vregbypass` (default `1'h1`), `dppulldown`/`dmpulldown`, `txbitstuffen(h)`, `hostdisconnect`
  (RO status), `vbusvalid0` (RO), FS/LS transceiver bits (`fsdataext`/`fsse0ext`/`txenablen`,
  `fslsrcv`/`fsvplus`/`fsvminus`), `siddq` (analog power-down), `testburnin`, PLL tune fields
  (`pllitune`/`pllbtune`/`pllptune`, default `4'hC`=4x), `compdistune` (disconnect-threshold,
  default `3'h3`=0%).
- **`apb parity check` page** (`0x1270_0600`-`0x060F`, ln 1744-1786): AXI-master
  fault-injection register set (`usb_m_awready_inj/wready_inj/bvalid_inj/bctrl_inj/arready_inj/
  rvalid_inj/rctrl_inj/rdata_inj`, all RW) paired with matching W1C interrupt-status shadow
  registers (`..._insts`) — a design-for-test block for injecting/observing AXI-response faults,
  useful for negative/error-injection DV.

**Cross-reference note**: this document is the ONLY one of the four USB-category sources that
gives byte-level detail for the USB3/USB2 PHY analog control surface; `register__ssvout_0806.xlsx`
never touches PHY internals at all (its lowest-level reference to USB is just the `usb0_clken`/
`usb1_clken`/`mswrst[3:4]` bit-indexed handles). Treat `USB_Reg_260727.docx` as authoritative for
PHY/wrapper CSRs and `register__ssvout_0806.xlsx` as authoritative for how usb0/usb1 plug into
the SS_VOUT bus-matrix/interrupt-aggregation fabric — they do not overlap or conflict.

---

## 3. `register__ssvout_0806.xlsx` — SS_VOUT subsystem-level register set (hosts usb0/usb1)

**What it is**: the SS_VOUT ("VideoOut") subsystem's own internal control-plane registers —
interrupt aggregation, ring-buffer/stream-buffer management, AXI bus-matrix arbitration, and
per-sub-module (mac0/mac1/pcie/**usb0/usb1**/mipitx) clock+reset — as opposed to
`USB_Reg_260727.docx`'s per-instance USB CSR pages. **This is a different register domain from
`USB_Reg_260727.docx`; do not conflate them** — `USB_Reg_260727.docx` is "inside" usb0/usb1;
this file is "around" them.

**Where it lives**: `D:\DV\Task\USB\DOC\register__ssvout_0806.xlsx`

**Sheets and base addresses** (all 256-byte pages except `reg_str`/`reg_trb`):

| Sheet | Base | Content |
|---|---|---|
| `ss_vout_reg00` | `0x1200_0000` | top interrupt/CQ-INT/reset/clock/probe/date (70 rows) |
| `ss_vout_reg01` | `0x1200_0100` | AXI write/read arbiter + device bus-matrix control (35 rows) |
| `ss_vout_reg02` | `0x1200_0200` | ring-buffer read/write level-detect config (67 rows) |
| `ss_vout_reg03` | `0x1200_0300` | (67 rows, not read in depth this pass — same family as reg02) |
| `ss_vout_reg_str` | `0x1200_02/4/5/600` (note: "duplicate Address" col says `0x12000X00, X=4/5/6` for stream0/1/2) | per-stream config (64 rows) |
| `ss_vout_reg_trb` | `0x1201_0000` | TRB (transfer-request-block?) engine, incl. `trb_axid_mask` (58 rows, 512-byte page) |

**Key registers extracted**:

- `0x0000~8` `ss_vout_intevt` RWC 73-bit interrupt-status register (bits span a `~[8]` byte
  range = 9 bytes for 73 bits), default `0x0`. Bit layout: `[3:0]/[7:4]/[11:8]`=str0/1/2 input
  stream {SOF,SOL,EOF,EOL}; `[15:12]/[19:16]/[23:20]`=str0/1/2 output stream same nibble layout;
  `[39:24]`=ring-buffer-0..15 read-half-level event; `[55:40]`=ring-buffer-0..15
  write-half-level event; `[56]`=top register-guard violation; `[57]`=AXI read-arbiter error;
  `[58]`=AXI write-arbiter error; `[59]`=stream-buffer AXI4 write error; `[60]`=stream
  burst-cross-packet error; `[61]`=stream under-run; `[62]`=stream cmd hsize error;
  `[63]`=buffer-id error; `[64]`=buffer sequence error; `[65]`=pkmode-changed-while-busy;
  `[66]/[67]`=AW/AR burst exceeds ring end; `[68]/[69]/[70]`=three distinct timeout classes
  (Grant-No-Valid, Backpressure, Busy); `[71]`=reserved; `[72]`=ring-oscillator done.
- `0x0010`/`0x0020` `ss_vout_irqen`/`ss_vout_fiqen` — same 73-bit map, RW enables.
- `0x0030` `ss_vout_esmen` [6:0] RW default `0x0` — ESM report enable, drives `ctl_esmerr` (the
  same signal `PAISB_Global_Reg`'s `ssvout_esmerr`/`ssvout_esmen` at `0x02_0221x` consumes).
- `0x0040`-`0x004F` 16× `cqintNNsel` [6:0] RW default `0x7F` — per-CQ interrupt-source select,
  choosing 1 of ~73 events (0-11=strin, 12-23=strout, 24-55=ring-buffer, 56-67=err, 68-71=timeout,
  72=ringosc, 73-127=none).
- `0x0050~1`...`0x006E~F` 16× `cqintNNen` [11:0] RW default `0x0` — **per-CQ interrupt-source
  enable mask**, `[0]`=ss_vout int, `[1]`=pkt int, `[2]`=trb int, `[4]`=mac0, `[5]`=mac1,
  `[8]`=pcie, **`[9]`=usb0, `[10]`=usb1**, `[11]`=mipitx.
- `0x0080` `mswrst` [5:0] RW default `0x0` — sub-module software reset: `[0]`mac0 `[1]`mac1
  `[2]`pcie **`[3]`usb0 `[4]`usb1** `[5]`mipitx.
- `0x0090`/`0x0091` `pclken`/`aclken` [5:0] RW default `0x3F` — APB/AXI clock enable, same 6-bit
  map as `mswrst`.
- `0x0097` `usb0_clken` [2:0] RW default `0x7`; `0x0098` `usb1_clken` [2:0] RW default `0x7` —
  independent per-instance clock-enable registers (3 bits each, all set by default).
- `0x00E0` `regclken` RW default `0x1` — page-0 gated-clock disable (present on every page,
  same pattern reused doc-wide across the whole PAISB family).
- `ss_vout_reg01` (`0x1200_0100`): AXI write/read arbiter reset/pause/priority/busy/error
  registers parameterized per-master `n=0..3` (`warb_pause[3:0]`, `warb_priority`
  4-bit-per-master, etc.), plus a **device bus-matrix** block: `devbm_rst`, `pause_dev[4:0]`
  (5 devices, n=0..4), `idle_dev`/`busy_dev` [9:0] (2 bits per device ×5). Also stream-buffer
  reset/route-select/debug-mode/pause/priority/timeout registers for 3 streams
  (`str_swrst[3:0]` includes a 4th bit `[3]`=stream-wrapper), `str_rout_sel` (0=AXI-slave-in-
  bus-matrix, 1=AXI-stream-master-to-MIPITX per stream).

**Cross-reference to `PAISB_Global_Reg_260731.doc`**: `mswrst`/`clken`/`usb0_clken`/`usb1_clken`
here are **subsystem-internal** fan-out registers gated by (i.e. downstream of) the chip-level
`swrst_set/clr_ss_vout` and `clken_set/clr_ss_vout` bits in the Global doc — two-tier reset/clock
architecture: chip-level enable/reset of the whole SS_VOUT block, then this doc's own
per-sub-module (usb0/usb1/mac0/mac1/pcie/mipitx) fan-out within it.

---

## 4. `SS_QDMA\PAISB_CQ_Reg_260810.docx` (latest of 3 dated copies) — Command Queue engine

**What it is**: the 16-instance programmable Command-Queue (CQ) micro-sequencer engine that
drives the QDMA subsystem (and, per §3's `cqint0Nen[9]/[10]` bits, can also be an interrupt
target/source for USB0/USB1 events at the SS_VOUT level). This is the CQ *register* spec, not
its instruction-set spec.

**Where it lives**: `D:\DV\Task\USB\DOC\SS_QDMA\PAISB_CQ_Reg_260810.docx` — **latest of 3 dated
copies** (`260603`, `260625`, `260810`); used per task instructions. Cover: "Preliminary", Aug 8
2026, **Version 0.3** printed on the cover, but the revision-history table (ln 11-21) actually
lists a further **0.4 "Fixed a typo" (2026/08/10, p.11)** entry after 0.3 — i.e. the file
you have is really rev 0.4 content with a stale 0.3 cover-page version string. Full revision
history: `0.1` File Creation (2026/06/03) → `0.2` "Fixing minor issues" (2026/06/25) → `0.3`
"Add cqprot reg" (2026/08/03, p.19) → `0.4` "Fixed a typo" (2026/08/10, p.11).

**Version-diff findings (earlier copies genuinely differ — captured per task instructions):**

`260603`→`260625` diff is dominated by table-reflow noise from a table-structure edit (~3270 of
~2341 lines differ under naive diff), and the changelog for `0.2` says only "Fixing minor
issues" with no page cited — evidence suggests this was largely formatting/wording cleanup, not
a register-map change; not independently verified line-by-line given volume, but no register
address/bit/reset delta was spotted while sampling.

`260625`→`260810` diff is small and **fully meaningful** (only 2 real deltas beyond the cover
date/version/changelog lines):

1. **`rdytimeoutaddr` field was widened**, `0x010_1094~`:
   - v0.2 (`260625`): bits `[18:2]`, reset `0x1_FFFF`, **with an explicit erratum note**:
     *"NOTE: rdytimeoutaddr\[18:2\] can only represent register address \[18:0\]. Therefore, it
     cannot correctly indicate Vivanate(VIP) registers which is in the range
     0x8_0000~0xF_FFFF."*
   - v0.3/0.4 (`260810`): bits **`[24:2]`**, reset **`0x7F_FFFF`**, erratum note **removed**
     (field now covers the full 25-bit APB address range, matching the separately-documented
     `moniaddr0l[23:0]` "now covering the full APB address range (25-bit)" language elsewhere
     in the same doc). **If any VIP/testbench code or checker was written against the v0.2
     18-bit `rdytimeoutaddr` field width or its "can't see 0x8_0000-0xF_FFFF" caveat, it is now
     stale — the current (260810) doc has fixed exactly that limitation.**
2. **New register added in v0.3**: `cqprot[2:0]` at `0x010_121C+base`, RW, default `0x2`.
   "Protection attribute carried on this CQ's APB accesses (APB PPROT\[2:0\]). Set per CQ before
   it runs." `[0]` privilege (0=normal,1=privileged), `[1]` NS (0=secure,1=non-secure), `[2]`
   instr (0=data,1=instruction). Note: "Under Secure lock, a CQ whose \[1\]=1 (non-secure)
   cannot access the CQ register space." — a genuine new security-attribute register absent
   from the two earlier dated copies entirely.

**Top-level address map** (ln 22-56, this is the source of the §0 cross-reference table above).

**CQ Mailbox** (ln 63-73): `0x010_2000`-`0x010_3FFF`, RW, "General purpose register (8KB)",
65536-bit-wide notional field `Mailbox[65535:0]` (i.e. the whole 8KB region is addressable as
one big RW mailbox memory).

**"To CPU interrupt status" register bank** (base `0x010_1000`, ln 82-250) — 88 discrete
interrupt-status bits (`cqintstatus[87:0]`, RWC, split across 9 byte/word registers
`0x010_1000`-`0x010_1008`): `[15:0]`=per-CQ "job done" (CQ0-CQF), `[31:16]`=per-CQ
"to-CPU software interrupt", `[39:32]`=4×(write/read)-monitored-address-region events,
`[55:40]`=per-CQ "instruction execution time-out", `[59:56]`=4×"HUM succeeded to apply for a
hardware unit" (per CPU channel), `[70:64]`=engine-level events (job-section-fetched,
arbiter-logger-done, invalid-AXI-read-address, arbiter-logger-choke-threshold,
apply-without-authorization / release-without-authorization errors — each cross-references a
specific `0x010_119C/9D`-family status register, "register access violation (aborted by
register guard)", "SMEM-read pre-buffer full"), `[87:72]`=per-CQ error interrupt (each
cross-references its own `0x010_119X` and `0x010_11AX` status/log registers). Plus
`cqapberrint` (`0x010_100B[0]`, RWC) = "register APB interface ready time-out".

**"To CQ interrupt status" bank** (base `0x010_1010`, ln 254+): `tocqNintstatus[15:0]` per CQ
— peer-to-peer CQ-to-CQ software interrupt matrix (CQ0-CQF can each software-interrupt any
other CQ).

**Software-reset block** (`0x010_1060`-`0x010_1061`, ln 826-850): `dramifrst`
(reset AXI-read channel that fetches CQ job sections from SMEM), `cqbuffrst` (reset CQ job
buffer write arbiter grant/history + CPU write-data staging), `apbrst` (W, reset register-APB
interface to primary modules), `apbabtrst` ("write 1 and KEEP 1 to hold register APB arbiter and
CQ-side APB arbiter in reset; write 0 to release" — a hold/release pair, not a pulse),
`humabtrst` (reset HUM arbiter — "clears all 64 hardware-unit occupancy states, owner records,
and HUM apply/release error flags"), `abtlogrst`. Then `0x010_1061`: `rprst` (default `1`!
"reset abtlogger status" — the ONLY reset-class bit in this block that defaults active/1
instead of 0), `rpmode` (0=latch-on-first-occurrence-until-cleared, 1=toggle-every-occurrence).
`0x010_1062~3` `inschken[15:0]` RW default `0xFFFF` — per-CQ "pause CQ on instruction format
error" enable (enabled for all 16 CQs by default); doc explicitly notes "error status and
interrupt will still work, even if inschken=0" (i.e. disabling the pause doesn't disable error
reporting, only the halt-on-error behavior).

**CQ core control registers** (base offsets per CQ, ln 2058-2194) — **16 identical 0x20-byte
(32-byte) per-CQ blocks**, `base = 0x000, 0x020, 0x040, ... 0x1E0` for CQ0..CQF. Per-CQ fields
(all at `0x010_12xx+base`):
- `0x00+base`: `cqcorestatus_0`[0] RW "0=disable/1=enable CQ", `cqcorestatus_1`[1] R "CQ
  waiting for event", `bp_halt`[2] R "halted at breakpoint".
- `0x01+base`: `cqrst`[0] RW, `cqpause`[1] RW, `cq_step`[2] WS (single-step while halted),
  `cq_resume`[3] WS (resume at full speed from breakpoint), `CQm_to_CPU_swint`[4] WS
  (`cqtocpu_swint`).
- `0x02~03+base`: `CQm_to_CQn[15:0]` WS — this CQ's software-interrupt-another-CQ vector.
- `0x04~07+base`: `cqbaseaddr[31:2]` RW — the job-program base address in SMEM (byte-based,
  4-byte aligned).
- `0x08~0B+base`: `cqcurcmddramaddr[31:2]` R — current-instruction DRAM fetch address.
- `0x0C~0F+base`: `cqcurcmd[31:0]` R — current-instruction raw word (debug visibility).
- `0x10~13+base`: `cqcmdtimernum[24:0]` RW default `0x1FF_FFFF` — watchdog timeout threshold in
  cycles; formula given: `time-out length = (cqcmdtimernum+1) / f24m (=25MHz)`. `[31]`
  `cqcmdtimermode` RW — 0=timer resets after every instruction, 1=timer resets only at CQ-job-
  done or on disable.
- `0x14+base`: `sectionvldmode`[0] RW default `1` — "Reserved for future use; currently has no
  effect on CQ behavior" (explicitly a dead/vestigial bit per the doc's own text — worth
  knowing so a checker doesn't chase a phantom behavior). `randomallocate`[1] RW default `1` —
  "the job buffer requires a section jump's target to match the section currently being filled
  before proceeding" when set; bypassed when cleared.
- `0x15+base`: `arqos_reg[3:0]` RW — AXI AR-channel QoS for this CQ.
- `0x1C+base`: **`cqprot[2:0]`** RW default `0x2` — new in v0.3, see version-diff above.

**CQ core internal registers** (ln 2196-2233, per-CQ, `+base`): `cq_r0`..`cq_r15` — a 16-entry
general-purpose register file (each R, mostly `0x0` default). `cq_r12[31:0]` is special:
`[3:0]`=CQID (self-identifying which CQ this belongs to), `[12:8]`=ALU flags `N,Z,C,V,G`,
`[31:16]`=`Abase[27:12]` (current ABASE_REG address, upper bits). `cq_r15[31:0]` defaults to
`0x4` (not 0 — worth noting, likely an initial PC/stack-pointer-like value).

**CQ JOB SRAM** (ln 2235-2245): `0x010_1600`-`0x010_167F` (128 bytes), RW,
`CQ_job_section[1023:0]` — "Use jobsecsel, jobpartsel, and jobsramwenable to access a desired
section of job. Use an address in multiple of 4 to access 4 bytes at a time." — direct-access
window into the CQ program-instruction SRAM.

**Other sections read but only structurally summarized (present, not exhaustively
transcribed in this report)**: "APB arbiter history" (`0x010_1068`-`106F`, 8× 5-bit history
records identifying which of 19 possible masters — CPU/MCU/APB_PORT1/CQ0-F — won each of the
last 8 arbitrations, oldest-history semantics explicitly documented), "register region to
monitor" (4 configurable address-range watchpoints, 25-bit addresses, `0x010_1070`+), "Hardware
unit management" (`0x010_1100`+, a 4-CPU-channel-and-64-hardware-unit apply/release/ownership
tracking block: `cpuhumdevid`/`cpuhumctrl` per channel, `cpuhumapply[3:0]` status,
`humstate_dev_N` occupancy bitmaps for 64 devices, `humrecord_devN[4:0]` ownership-encoding
0-3=CPU-ch0-3, 4-19=CQ0-CQF), "Arbiter logger", "CQ HUM error status" (×2, CQ-side and
CPU-side), "Instruction format error status", "Multiple WFE", "Parser for CQX", "CQ SRAM BIST",
"CQ SRAM mode control", "Direct access to CQ job SRAM", "Lock register APB requester", "CQ
probe", "Date code".

---

## 5. `SS_QDMA\PAISB_SS_QDMA_Reg_260605.docx` — SS_QDMA subsystem glue (only 1 dated copy)

**What it is**: the short (155-line) top-level glue-register doc for the SS_QDMA subsystem
itself — analogous in role to `register__ssvout_0806.xlsx` for SS_VOUT, but for the CQ+DMA
compute subsystem. Fully read (complete, not excerpted).

**Where it lives**: `D:\DV\Task\USB\DOC\SS_QDMA\PAISB_SS_QDMA_Reg_260605.docx`

**§1 Address Map** (ln 3-17): "SS_QDMA sub-system control registers start at base address
`0x1030_0000`. `ss_qdma_reg00` holds interrupt, CQ-INT, reset and clock control; `ss_qdma_reg01`
holds the AXI master arbiter control. The two modules have their own register spaces: the CQ at
`0x1010_0000` and the DMA at `0x1031_0000` onward, documented separately." (This sentence is the
key evidence used in §0's address-formula triangulation.)

**`ss_qdma_reg00`** (base `0x1030_0000`, ln 19-125): `ss_qdma_intevt[14:0]` RWC default `0x0` —
`[0]`=register-guard violation, `[1]-[8]`=CQ/DMA AXI write/read error (bid/rid empty vs
mismatch, 4 combinations ×2 for CQ vs DMA), `[14:9]`=reserved. Matching `ss_qdma_irqen`/
`ss_qdma_fiqen`. 16× `cqintNNsel[3:0]` RW default `0xF` (select 1 of: 0-8 map to
`ss_qdma_intevt` bits, 15=none). 16× `cqintNNen[1:0]` RW default `0x0` — `[0]`=ss_qdma enable
of CQ-INT, `[1]`=DMA enable of CQ-INT. `cqintmode[15:0]` RW — per-CQ OR/AND aggregation.
`mswrst[1:0]` RW default `0x0` — `[0]`=CQ, `[1]`=DMA. `pclken`/`aclken`/`xtlclken`[2:0] RW —
`[0]`=SS_QDMA-top `[1]`=CQ `[2]`=DMA (xtlclken explicitly documented as the 25MHz Xtal clock).
`prbmode` `0x00F1` options include `8`=cq probe, `9`=dma probe. Date-code registers
`0x00FC`-`0x00FF` (MONTH=`06` DATE=`01` HOUR=`10` MIN=`09` as literal defaults — i.e. this
doc's own generation timestamp baked into the register spec's date-code default, June 1st
10:09, consistent with the doc's June-2026 origin).

**`ss_qdma_reg01`** (base `0x1030_0100`, ln 127-155): two AXI arbiters (write, read) merging CQ
and DMA onto one shared external AXI-4 bus. `warb_rst`/`rarb_rst`[0] RW. `warb_pause`/
`rarb_pause`[1:0] RW **default `0x3`** (both CQ and DMA sources paused at reset — doc explicitly
warns: **"software must clear them during the initial flow"**, i.e. a required bring-up step,
not optional). `warb_priority`/`rarb_priority`[7:0] RW, 4-bit-per-source (CQ=`[3:0]`,
DMA=`[7:4]`). `warb_busy`/`rarb_busy`[1:0] R. `warb_error`/`rarb_error`[3:0] R (2-bit-per-source
error code). `regclken` `0x00E0`.

**Cross-reference confirmed against §4**: "the CQ at 0x1010_0000" here matches
`PAISB_CQ_Reg_260810.docx`'s own top-level map bucket (`0x01XXXXX`→local `0x0100000`→system
`0x1010_0000`) exactly — same document family, internally consistent.

---

## 6. `SS_QDMA\PAISB_DMA_Reg_260605.docx` (only 1 dated copy) — DMA sub-module register map

**What it is**: the 8-channel streaming-DMA engine that sits inside SS_QDMA alongside the CQ.
Fully structured, 749 lines converted; read start-to-finish.

**Where it lives**: `D:\DV\Task\USB\DOC\SS_QDMA\PAISB_DMA_Reg_260605.docx`

**§1 Address Map** (ln 3-31): base `0x1031_0000`, divided into 5 shared "topctl" 256-byte pages
(`dma_reg00`-`dma_reg04`) plus 8 per-channel 256-byte pages (`dma_core[0..7]` at
`0x1031_8000 + n*0x100`, n=0..7, i.e. `0x1031_8000`-`0x1031_87FF`).

| Page | Base | Content |
|---|---|---|
| `dma_reg00` | `0x1031_0000` | interrupt event/enable (IRQ/FIQ/ESM), sub-module reset & clock, probe, date |
| `dma_reg01` | `0x1031_0100` | CQ-INT select / enable / mode (2-layer: per-CQ 80-bit enable × AND/OR mode × 82-way select) |
| `dma_reg02` | `0x1031_0200` | AXI & MailBox arbiter, stream control, SRAM, BIST |
| `dma_reg03` | `0x1031_0300` | origin (input-side) stream info: framecnt/hsize/line-CRC/frame-CRC per tid |
| `dma_reg04` | `0x1031_0400` | output-side stream info, identical layout to reg03 |
| `dma_core[n]` | `0x1031_8000+n*0x100` | per-channel control/status/CRC-monitor (n=0..7) |

**`dma_reg00`** (ln 33-123): four 32-bit "input stream event" registers
(`dma_strin_intevt0..3`, RWC) each packing 8 tid's ×4-bit {SOF,SOL/SOP,EOF,EOL/EOP} = covers
tid 0-31 across the 4 registers; matching 4× `dma_strout_intevt0..3` for output side; plus
`dma_intevt[15:0]` (`[7:0]`=ch0-7 source-read-done, `[15:8]`=ch0-7 destination-write-done) and
`dma_err_intevt[31:0]` (`[7:0]`=ch0-7 source error, `[15:8]`=ch0-7 destination error,
`[23:16]`=ch0-7 register-guard violation, `[24]`=DMA-top register-guard violation, `[25]/[26]`=
source-stream-0 multi-/null-destination error, `[27]/[28]`=source-stream-1 same). Every event
register has matching `_irqen`/`_fiqen` shadow registers at `+0x40`/`+0x80` (explicitly stated:
"event block is at 0x00, IRQ enable at +0x40, FIQ enable at +0x80, ESM enable at +0xC0 region"),
plus `dma_err_esmen` at `0x00E4~7`. `mswrst[7:0]` (`0x00D0`, per-channel reset), `mclken[7:0]`
(`0x00D4`, default `0xFF` — all 8 channel clocks enabled at reset), `mtoken[7:0]` (`0x00D8`,
per-channel secure token).

**`dma_reg01`** (ln 125-263): documented mechanism (ln 127): "Each CQ has an 80-bit enable
(`cqintNNen`, dma_intevt\[16\] + org stream evt\[32\] + out stream evt\[32\]) and a mode bit
(AND/OR) that aggregate the enabled events into one signal; `cqintNNsel` (7-bit, one of 82) then
selects either an individual event, the aggregated signal, or none for that CQ." Concretely:
16× `cqintNNsel[6:0]` RW default `0x51` (=81 decimal = "none" per the encoding table: 0-15=
`dma_intevt[0..15]`, 16-47=org-stream-event[tid0..31], 48-79=out-stream-event[tid0..31],
80=aggregated-int-of-this-CQ, 81=none) — **so the power-on default routes NO DMA event to any
CQ**; software must actively select a source. 16×3 enable-group registers per CQ
(`cqintNNen0/1/2`, 96 registers total, all default `0x0`) plus 16-bit `cqintmode[15:0]`
(OR=0/AND=1 per CQ).

**`dma_reg02`** (ln 265-359): AXI write/read arbiters for the 8 DMA channels
(`warb_axi_pause`/`rarb_axi_pause`[7:0] **default `0xFF` — all 8 channels paused at reset**,
`warb_axi_priority`/`rarb_axi_priority`[31:0] 4-bit-per-channel), 2 MailBox arbiters
(`mbwarb`/`mbrarb`, 1-bit-per-channel priority), `arben[3:0]` (master enable for
write-arb/read-arb/mailbox-warb/mailbox-rarb, **default `0x0` — all four arbiters disabled at
reset**). Stream-pipe block: `cfg_stren[2:0]` (per-stream enable), `cfg_src_rst[1:0]`/
`cfg_dst_rst[2:0]`, `cfg_src_pause[1:0]` default `0x3`/`cfg_dst_pause[2:0]` default `0x7` (**all
sources paused at reset**), per-source-group pause/priority for a 14-source output arbiter
(`DSRCN=14: m0:ch0-3+s0, m1:ch4-7+s1, m2:ch2/3/6/7`, defaults `0x1F` pause / `0x0` priority),
`cfg_src_idmask[47:0]` (6-bit-per-channel ×8 tid/tdest match mask). SRAM arbiter
(`sram_arb_rst/en`, `sram_arb_priority[15:0]`), SRAM power (`sram_disgated/dslp/slp/sd[2:0]`
per-bank ×3 banks), SRAM BIST (`bistmode`/`memgroupsel`/`bistfinish`/`bistfail`). **Doc's own
explicit bring-up warning (ln 267): "Note the safe defaults: arben=0, sram_arb_en=0,
cfg_src_pause=0x3, cfg_dst_pause=0x7, arbiter pause=0xFF — software must release these in the
initial flow."** — this is a required, documented bring-up sequence dependency.

**`dma_reg03`/`dma_reg04`** (ln 361-632): per-tid (0-31) statistics, 16-bit values packed 2-per-
32-bit-register (low half=even tid, high half=odd tid): `org_framecnt_NN_NN+1`,
`org_hsize_NN_NN+1`, `org_lcrc_NN_NN+1` (line CRC), `org_fcrc_NN_NN+1` (frame CRC) — 16 registers
×4 statistic types = 64 registers for the origin (input) side; `dma_reg04` mirrors this
identically for the output side (doc explicitly states "same layout as reg03").

**`dma_core[n]`** (ln 633-749, per-channel, 256-byte page, base `0x1031_8000+n*0x100`) — the
single most operationally important register page for DMA verification:

| Off | Bit | Attr | Name | Reset | Meaning |
|---|---|---|---|---|---|
| 0x00 | 5:0 / [7] | R | dma_chx_id / dma_chx_token | 0x0 | Channel self-ID / token |
| 0x04 | 5:0 | R | sts_src_error | 0x0 | `[0]`err `[1]`err-config `[2]`err-trigger `[3]`err-response `[4]`err-eol `[5]`err-lol |
| 0x05~6 | 9:0 | R | sts_dst_error | 0x0 | `[0]`err `[1]`config `[2]`bvalid-resp `[3]`eol `[4]`lol `[5]`pipe-error `[9:6]`pipe-error-state |
| 0x08 | 1:0 | W | trigger | 0x0 | `[0]`source-trigger `[1]`destination/pipe-trigger — **2-stage trigger** |
| 0x09 | 2:0 | R | sts_busy | 0x0 | `[0]`src_busy `[1]`dst_busy `[2]`pipe_busy |
| 0x0C/0x0D | 7:0 | RW | axi_src_mlen / axi_dst_mlen | 0x3 | AXI4 max burst length, read/write |
| 0x10 | 2:0 | RW | srcsel | 0x0 | 0=SMEM(AXI4) 1=AXI-Stream 2=Mail-Box 3=PIO 4=Register-Fill |
| 0x14~6 | 19:0 | RW | src_size | 0x10000 | source byte-count (total transfer = Σ src_size) |
| 0x18~B | 31:0 | RW | src_addr | 0x20000000 | source byte-address (used when srcsel=0 or 2) |
| 0x1C | 8:0 | RW | src_aruser | 0x6 | `[3:0]`TZC400-ID `[7:4]`ring-buffer-select(1-of-16) `[8]`bypass-vs-ring-buffer-mode |
| 0x1E | 3:0 | RW | src_arqos | 0x0 | read QoS |
| 0x20 | 0/1 | RW | src_str_chken / src_tlast_mode | 1 / 0 | tid/tdest check enable; tlast-by-count(0) vs from-axi-stream(1) |
| 0x21/0x22/0x23 | 5:0 | RW | src_tid / src_tid_mask / src_tdest_mask | 0 / 0x3F / 0x3F | stream tag matching |
| 0x24~7 | 31:0 | RW | src_fill_data | 0x0 | fill pattern (srcsel=4) |
| 0x30 | 2:0 | RW | dstsel | 0x0 | 0=SMEM 1=AXI-Stream 2=Mail-Box 3=PIO 4=none |
| 0x34~6 | 19:0 | RW | dst_size | 0x10000 | dest byte-count |
| 0x38~B | 31:0 | RW | dst_addr | 0x20000000 | dest byte-address (dstsel=0 or 2) |
| 0x3C | 8:0 | RW | dst_awuser | 0x0 | same ring-buffer/bypass scheme as src_aruser |
| 0x3E | 3:0 | RW | dst_awqos | 0x0 | write QoS |
| 0x40/41/43 | | RW | dst_str_chken/tlast_mode, dst_tid, dst_tdest | 0 | dest tag setting |
| 0x44~6 | 19:0 | RW | dst_tuser | 0x0 | `[0]`SOF `[1]`EOF `[2]`SOL/SOP `[3]`EOL/EOP `[19:4]`beat-count/HSIZE |
| 0x50~3/0x54/0x58~B/0x5C | | W/R | piowr_data, piowr_ready/full, piord_data, piord_valid/empty | | PIO FIFO ports, 1/2/4-byte writes supported |
| 0x60 | 7:0 | RW | swrst | 0x0 | `[0]`src `[1]`dst `[2]`pipe `[4]`monitor-crc32 `[5]`monitor-checksum |
| 0x68 | 0 | RW | disgclken | 0x1 | 0=gated-clock 1=always-on |
| 0x80 | 0/1 | RW | mon_crc_en / mon_checksum_en | 0 | in-core CRC32/checksum monitor enable |
| 0x82 | 0/1 | R | mon_crc_idle / mon_checksum_idle | 1 | monitor idle status |
| 0x84 | 1:0 | RW | mon_crc_mden | 0 | `[0]`line/packet-crc32 `[1]`frame-crc32 (supports restore) |
| 0x88 | 0 | W | mon_crc_restore | 0 | write-1-active |
| 0x8C~F | 31:0 | RW | mon_crc_restore_din | 0xFFFFFFFF | frame-CRC seed for restore |
| 0x90~3/0x94~7 | 31:0 | R | mon_crc32_line / mon_crc32_frame | 0 | latched CRC32 results |
| 0x98~B/0x9C~F | 31:0 | R | mon_cur_crc32_line / mon_cur_crc32_frame | 0xFFFFFFFF | in-flight running CRC32 |
| 0xA0~3/0xA4~5 | 31:0/15:0 | R | mon_checksum32 / mon_checksum16 | 0 | checksum results |

**Cross-reference / refinement: `register__ssqdma_dma_260719.xlsx` (latest of 2 dated xlsx
copies) is MORE complete than this docx for the per-channel page** — see §7 below for the
concrete deltas (renamed doc-facing field names, two extra fields the docx omits entirely:
`src_arprot`/`src_arcache`/`dst_arprot`/`dst_arcache`, and a wholly new `dst_rbc_thres`
register at offset `0xB0` that doesn't exist in this `260605` docx at all).

---

## 7. `SS_QDMA\register__ssqdma_dma_260719.xlsx` (latest of 2 dated copies) — DMA reg map, Excel form

**What it is**: the machine-readable (spreadsheet) counterpart to §6, carrying an extra column
(`RTL Register Name`) that the prose docx does not have, and evidently maintained on a
different/faster cadence than the docx (dated `260719` = Jul 19, vs. the docx's `260605` = Jun
5 — 6 weeks newer).

**Where it lives**: `D:\DV\Task\USB\DOC\SS_QDMA\register__ssqdma_dma_260719.xlsx` (latest;
`register__ssqdma_dma_260701.xlsx` is the earlier copy, diffed below).

**Sheets** (8 total, matching §6's page structure 1:1): `ss_qdma_reg00` (base `0x1030_0000`,
confirmed exact match to §5), `ss_qdma_reg01` (base `0x1030_0100`, confirmed match), `dma_reg00`
(base likely `0x1031_0000`, not independently re-verified byte-for-byte but structurally
matches), `dma_reg01`, `dma_reg02`, `dma_reg03`, `dma_reg04`, `dma_core_reg` (base `0x1031_8000`,
"duplicate Address" column states `0x10318X00` confirming the `+n*0x100` per-channel pattern
from §6 in a second, independent source).

**⚠ Meaningful delta vs. the earlier `260701.xlsx` copy** (full diff run; two classes of change):

1. **Doc-facing register-name cleanup in `dma_reg02` (7 registers renamed, `_str_` infix added
   to disambiguate from the identically-named per-channel `dma_core` fields) — but the
   underlying RTL Register Name column is UNCHANGED for all 7:**

   | Old "Doc Register Name" (260701) | New "Doc Register Name" (260719) | RTL Register Name (both) |
   |---|---|---|
   | `cfg_src_rst` | `cfg_str_src_rst` | `cfg_src_rst` |
   | `cfg_dst_rst` | `cfg_str_dst_rst` | `cfg_dst_rst` |
   | `cfg_src_pause` | `cfg_str_src_pause` | `cfg_src_pause` |
   | `cfg_dst_pause` | `cfg_str_dst_pause` | `cfg_dst_pause` |
   | `cfg_dst_s_pause_g0/g1/g2` | `cfg_str_dst_s_pause_g0/g1/g2` | `cfg_dst_s_pause_g0/g1/g2` |
   | `cfg_dst_s_prio_g0/g1/g2` | `cfg_str_dst_s_prio_g0/g1/g2` | `cfg_dst_s_prio_g0/g1/g2` |
   | `cfg_src_idmask` | `cfg_str_src_idmask` | `cfg_src_idmask` |

   **Practical implication**: `PAISB_DMA_Reg_260605.docx` (§6) uses the OLD (`260701`-era, no
   `_str_` infix) names throughout its `dma_reg02` section (verified: docx ln 304-324 uses
   `cfg_src_rst`/`cfg_dst_rst`/`cfg_src_pause`/`cfg_dst_pause`/`cfg_dst_s_pause_gN`/
   `cfg_dst_s_prio_gN`/`cfg_src_idmask` verbatim). So the docx's *documentation-facing* names
   are now stale relative to the newer xlsx, **even though the actual RTL signal names never
   changed** — if a testbench/checker cites a register by its "doc name," cite the RTL Register
   Name (which is stable across both dates) rather than the Doc Register Name (which is not),
   or note explicitly which doc vintage a "doc name" citation came from.

2. **New field added to `dma_core_reg`** (row count 109→110): `0xB0~3` `dst_rbc_thres` RW
   default `0x400`, "destination ring buffer control threshold value", RTL name
   `dst_rbc_thres`. **This register does not exist at all in `PAISB_DMA_Reg_260605.docx`'s
   per-channel table (§6)** — the docx's per-channel map jumps straight from `mon_checksum16`
   (`0xA4~5`) to the reserved block (`0xF0`+) with nothing at `0xB0`. The xlsx is strictly newer
   here.

**Additional per-channel fields present in the xlsx but absent from the `260605` docx
entirely** (found while reading `dma_core_reg` full content, not just the diff): at offset
`0x1E`, alongside `src_arqos[3:0]` (present in both), the xlsx additionally has
**`src_arprot[6:4]` RW default `0x0`** ("source prot setting for read SMEM (AXI-4)") packed
into the *same byte*, plus **`src_arcache[3:0]` RW default `0x3`** at the next byte `0x1F`
("source cache setting"). Symmetrically for the destination side: **`dst_arprot[6:4]`** at
`0x3E` (alongside `dst_awqos`) and **`dst_arcache[3:0]`** at `0x3F`, both RW default
`0x3`/`0x0` respectively. **None of these four AxPROT/AxCACHE fields appear anywhere in
`PAISB_DMA_Reg_260605.docx`** — confirming the June docx's per-channel page is measurably less
complete than the July xlsx for AXI attribute (PROT/CACHE) control, in addition to missing
`dst_rbc_thres`. Any AXI-attribute-level DMA testbench/checker work should reference the xlsx,
not the docx, for the per-channel page.

---

## 8. `rtl_vip_scaledown_mapping.xls` — RTL LTSSM/USB timer scale-down ↔ SVT_USB VIP config mapping

**What it is**: a cross-reference spreadsheet mapping the DUT RTL's `ss_scaledown_mode`-gated
LTSSM/PRTSM/USB2-chirp timer constants to the corresponding Synopsys `svt_usb_*` VIP
configuration knobs, with concrete Default vs. Scaled numeric values for each. This is
explicitly a **timing/config cross-reference**, not a register-address map — but it is real
material named in the task and is exactly the kind of "which VIP knob corresponds to which RTL
constant, and what value" fact a DV engineer needs before trusting a scaled-mode simulation.

**Where it lives**: `D:\DV\Task\USB\DOC\rtl_vip_scaledown_mapping.xls`

**8 sheets, read in full**: `RTL and VIP` (105 rows), `Scaled VIP Variables` (126 rows),
`USB2-Device` (18 rows), `USB2-Host` (32 rows), `USB2-OTG` (102 rows, not exhaustively
transcribed here), `USB3-OTG3` (22 rows), `USB3-LTSSM` (18 rows), `USB3-SSIC` (58 rows).

**Sheet 1, `RTL and VIP`**: side-by-side RTL Verilog snippets (scale vs. non-scale expressions,
e.g. `ONE_MSEC = ... scale ? 'd10 : 'd1000`) against the matching `SVT_USB_*` macro-driven VIP
field and its Default/Scaled numeric pair. Representative entries (RTL constant → VIP field →
Default → Scaled):
- `RX_DET_ATTEMPTS` (scale?2:7) → `rx_detect_termination_detect_count` = `SVT_USB_RX_DETECT_TERMINATION_DETECT_COUNT` → 8.0 → 8.0 (**not actually scaled in the VIP despite RTL having a scale-down path** — a real Default==Scaled case worth flagging for anyone assuming everything scales uniformly).
- `RX_EQ_COUNT` (scale?8:66191) → `polling_rxeq_tseq_count` → 65536(10) → 8.0
- `LGEN_POLL_NUM`/`LGEN_POLL_SENT` → `polling_lfps_sent_count`/`polling_lfps_sent_after_received_count` → 16.0/4.0 → 3.0/2.0
- `LFPS_RESET_RX_MS` (scale?70:20, "Detect warm reset for US only") → `treset_burst_min/max` → 80ms/120ms → 0.8ms/1.2ms
- `U1_NORESP_TIME_CLKS`/`U2_NORESP_TIME_US`/`U3_NORESP_TIME_MS` → `u1/u2/u3_no_lfps_response_timeout` → 2ms/2ms/10ms → 20us/20us/100us
- `LT_RX_DET_QUIET_MS`/`LT_SSI_QUIET_MS`/`LT_POLL_LFPS_MS`/`LT_POLL_ACTIVE_MS`/`LT_POLL_CONFIG_MS`/
  `LT_POLL_IDLE_US`/`LT_RECOV_ACTIVE_MS`/`LT_RECOV_CONFIG_MS`/`LT_RECOV_IDLE_US`/`LT_HRESET_ACT_MS`/
  `LT_HRESET_EXIT_US` — the full LTSSM per-state timeout family, each with an explicit RTL
  scale/non-scale pair and its VIP-side timeout knob (`rx_detect_quiet_timeout`,
  `ss_inactive_quiet_timeout`, `polling_lfps_timeout`, `polling_active_timeout`,
  `polling_configuration_timeout`, `polling_idle_timeout`, `recovery_active_timeout`,
  `recovery_configuration_timeout`, `recovery_idle_timeout`, `hot_reset_active_timeout`,
  `hot_reset_exit_timeout`).
- Explicit note in-sheet: *"This is for USB3.0 ECN20, and is used only for a downstream port.
  The default behaviour does not use this. To enable this, set **GUCTL.DS_RXDET_MAX_TOUT_CTRL**"*
  — this is the **only place in this entire extraction pass that names a specific DWC_usb31
  core register+field (GUCTL.DS_RXDET_MAX_TOUT_CTRL) with its functional meaning**, even though
  (per §2's gap) no document gives GUCTL's address/bit-position. Worth cross-referencing
  against the databook/programming-guide once accessible.

**Sheet 2, `Scaled VIP Variables`**: two flat columns of already-pre-scaled `svt_usb_*`-style
config assignments — left column "for SS operation" (e.g. `credit_hp_timer = 50us`,
`hot_reset_active_timeout = 130us`, full list of `lfps_t1x_t1x_uN_min/max` LFPS handshake
timing, `polling_*`/`recovery_*` timeouts, `u1/u2/u3_exit_*`, `ux_exit_timer_timeout = 6000us`,
`usb_ss_symbol_clock_period = 400ps`); right column "for 2.0 operation" (USB2 chirp/timing
constants: `tattdb`, `tdchbit=750ns`, `tdchse0=1.5us`, `tdrst=115us` **if
`DWC_USB3_FREECLK_USB2_EXISTS` defined, else 15us** — an explicit ifdef-conditioned value pair
captured directly in the sheet, `twtrsths=450us`, etc.).

**Sheet 3, `USB2-Device`** (File = `DWC_usb3_u2dssr.v`): device-mode chirp/reset timing, each
row giving the literal RTL `always`/`assign` snippet, the USB-spec min/max, and the RTL's
device-mode-scale-down vs. fullscale numeric result, cross-referenced to a USB-spec parameter
name (TDCHSE0, TDETRST, TWTRSTHS, TUCH, TWTFS, TFILT/TDCHBIT). Notable: `dev_chirp_time`
(TUCH) full-scale differs by `DWC_USB3_FREECLK_USB2_EXISTS`: 2.0ms baseline vs "Upto 3.0ms if
...EXISTS", and an explicit doc footnote: *"If GUSB2PHYCFG\[XCVRDLY\] is set, then the chirp
duration is reduced by 2.5us for both fullscale/scaledown modes"* — a second concrete
core-register-field name (**GUSB2PHYCFG.XCVRDLY**) with documented functional effect, again
un-backed by an address in any provided doc.

**Sheet 4, `USB2-Host`** (File = `DWC_usb3_u2prtsm.v`): host-mode chirp/reset timing —
`reset_duration` (TDRSTR, USB2.0 §7.1.7.5, "resets from root ports have a duration of at least
50 ms") → RTL scale-down 255us / fullscale 50ms; `chirp_det_time` (TFILT), `chirp_idle_time`
(TWTDCH), `chirp_j_or_k_time` (TDCHBIT), `chirp_done_se0time` (TDCHSE0), `revert_time` (TWTREV,
HS→FS revert, spec 3-3.125ms, RTL fullscale 4ms — **RTL is intentionally looser than spec max**,
doc comment: "This is ok to account for clock accuracy").

**Sheets 5-8** (`USB2-OTG`, `USB3-OTG3`, `USB3-LTSSM`, `USB3-SSIC`): same RTL-snippet ↔
VIP-field ↔ numeric-pair pattern, specialized to OTG role-swap timers, the second (`a3_`/`b3_`
port-A/port-B) LTSSM instance used for OTG3 dual-role testing, the primary LTSSM state-machine
table (a second, table-formatted restatement of the LT_* timers already in Sheet 1, with an
explicit `RxDetect.Quiet`/`Polling.LFPS`/`Polling.Active`/... state-name column this time), and
the SSIC (M-PHY-based) variant with its own scaled/non-scaled/SNPS-M-PHY-model-scaled 3-way
value split (e.g. `tRESET_DIFFN`: 100us(scaled) / 400us(SNPS-M-PHY-sim) / 70ms(non-scaled)) plus
inline RTL code fragments for `ifdef DWC_USB3_SNPS_MPHY_SIM_SUPPORT`-conditioned timer
variants.

**Use for DV work**: whenever a scaled-mode LTSSM/chirp timing checker or scoreboard needs a
concrete expected value (e.g. "how long should Polling.LFPS take in scaled-mode sim"), this
file is the primary source — it is more directly actionable than deriving the value from the
RTL parameter definitions by hand, since it already carries the paired VIP knob name.

---

## Summary of concrete, checkable claims (quick index)

- **usbswrst**: `0x1270_0034`, RW, 16 bits `[15:0]`, reset `16'h0`, 10 named sub-bit clock-domain
  resets. Source: `USB_Reg_260727.docx` ln 168. (Matches/confirms DUT-003.)
- **Port-1 base address**: **not resolved by any document in this set** — `USB_Reg_260727.docx`
  duplicates instance-0's `0x1270_0000`-`0x1273_FFFF` table verbatim for instance 1. (Directly
  relevant to DUT-007 — flag as an open documentation gap, not a resolved fact.)
- **GCTL / DCTL / DCFG / DSTS / GEVNTCOUNT / GSTS / DALEPENA**: **zero address/bit/reset/access
  data found** in any doc/excel in this category. Only functional cross-references exist
  (`DCFG.DEVSPD` named once in `USB_Reg_260727.docx`; `GUCTL.DS_RXDET_MAX_TOUT_CTRL` and
  `GUSB2PHYCFG.XCVRDLY` named once each in `rtl_vip_scaledown_mapping.xls`). Authoritative source
  (`DWC_usb31_programming.pdf`) is **absent from the provided material**; the present
  `DWC_usb31_databook_WM-25380.pdf` is a different document and is password-locked against text
  extraction.
- **SoC address formula**: `system = 0x1000_0000 | local28`, with `local28` nibble decode per
  §0's table — verified against 4 independent documents.
- **CQ engine**: 16 instances, each a 0x20-byte block at `0x010_12xx + n*0x20` (n=0..15), full
  register list in §4.
- **DMA engine**: 8 channels, each a 256-byte block at `0x1031_8000 + n*0x100` (n=0..7), full
  register list in §6/§7 (use §7's xlsx for AxPROT/AxCACHE/`dst_rbc_thres`, not present in the
  §6 docx).
- **Version deltas that matter**: CQ `rdytimeoutaddr` widened 19→25 bits between `260625`→`260810`
  (fixes a documented VIP-visibility gap); CQ `cqprot` register added in `260810`; DMA xlsx
  `260701`→`260719` renamed 7 doc-facing (not RTL) register names and added `dst_rbc_thres`.
