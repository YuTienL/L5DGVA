# Intake Extraction — Categories 7+8: DUT RTL / Registers / Interrupts, and IP Source/Model

Source root (remote Linux DV server, `host-c`, via `tools/remote/remote_exec.py`):
`/home/svcacct/DV/DUT/0820/dlan063/SIMV_GIT/`

Sub-trees examined:
- `RTLCAT/` — real DUT RTL (SoC integration + IP-level RTL, flattened per-block into `SS_*_ALL.v` / `TOP_ALL.v` files)
- `MODEL/` — IP behavioral model (`MODEL_ALL.v`, IP-specific includes)
- `MACRO/` — macro / PHY behavioral models (`MACRO_ALL.v`, hard-IP `.vp`/`.vp.vcs` files)

All line numbers below are exact `grep -n` / `sed -n` citations taken directly from the files on
the remote server in this session (not inferred from memory or from other agents' summaries).

---

## 1. Top-level module hierarchy (RTL)

Confirmed instantiation chain, `RTLCAT/TOP_ALL.v` and `RTLCAT/SS_VOUT_ALL.v`:

```
lan063                      (TOP_ALL.v:23023 — SoC top, "module lan063(")
 └─ gtop / gckrst / greg* / plltop / ion063 / ss_cpu / ss_mem / ss_gcon / ss_qdma / ss_vis / setop
 └─ ss_vout                 (TOP_ALL.v: instantiated as u_ss_vout, per TOP_ALL.v:25507 comment
                              "module ss_vout: included ether-mac/pcie/usb/mipi-tx"; port hookup
                              begins TOP_ALL.v:25528 `u_ss_vout(`)
      module ss_vout is DEFINED in SS_VOUT_ALL.v:8 ("module ss_vout #(")
      └─ u_usbtop            usbtop dual-instance array (SS_VOUT_ALL.v:4515 / :5060)
      └─ u_ss_vout_ctl       ss_vout_ctl  (SS_VOUT_ALL.v:5567) — top control/interrupt-enable regs
      └─ u_ss_vout_cqint     cqint        (SS_VOUT_ALL.v ~2296) — CQ event aggregator
      └─ u_apbsplit          apbsplit_rep (SS_VOUT_ALL.v:2192) — APB address decode fan-out to
                              PCIe/MAC0/MAC1/USB0/USB1/MIPITX/PKT/TRB/CTL sub-blocks
      └─ ss_vout_reg00..03, ss_vout_reg_str, ss_vout_reg_trb  — register-block modules
                              (SS_VOUT_ALL.v:6738,7509,7847,8043,8957,9369)
      └─ nic400_* (dozens)   — Arteris/ARM NIC-400 AXI interconnect fabric generated modules
                              (SS_VOUT_ALL.v:19328 onward) connecting SMEM/STR0-2/TRB/MAC0/MAC1/
                              PCIE/USB0/USB1 AXI master & slave sockets to the ss_vout crossbar
```

`ss_vout` is genuinely a **sub-system container**, not just USB: it multiplexes Ethernet MAC
(MAC0/MAC1), PCIe, USB (dual instance), MIPI-TX, a packet engine ("PKT"), a trace/debug ring
buffer ("TRB"), and its own control block ("CTL") behind one APB/AXI crossbar (comment at
TOP_ALL.v:25507).

### 1.1 `u_usbtop` instantiation — two configurations exist side by side

`SS_VOUT_ALL.v` contains **two mutually-exclusive `` `ifdef HAPS `` branches** for how the USB
IP is instantiated — this matters for anyone reading the file naively, since a single `grep -n
u_usbtop` returns both and they are NOT both active in the same build:

- **`` `ifdef HAPS ``** branch (`SS_VOUT_ALL.v:4503` opens the `ifdef`, instance header at :4515,
  usb1 tie-offs run from :4437 through ~:4568): single `usbtop` instance named `u_usbtop`
  (SS_VOUT_ALL.v:4515) driving **only usb0**; every
  `usb1_*` output is tied off with `assign usb1_xxx = 'h0;` (SS_VOUT_ALL.v:4915–4917 for
  `usb1_irq/usb1_fiq/usb1_esmerr`, and dozens more for AXI/JTAG/scan/PHY-scan ports through
  line ~565 of that region). This is the FPGA/emulation-prototype (HAPS) configuration — USB1 is
  simply absent from the emulated netlist.
- **`` `else `` (real ASIC / VCS simulation)** branch: a **true dual-instance array**,
  `usbtop ... ) u_usbtop[1:0] (` (SS_VOUT_ALL.v:5060), with per-port concatenation, e.g.
  (SS_VOUT_ALL.v:5069–5071):
  ```
  .usb_irq    ( {usb1_irq   ,usb0_irq}    ),   // Output [INTN-1:0]
  .usb_fiq    ( {usb1_fiq   ,usb0_fiq}    ),   // Output [INTN-1:0]
  .usb_esmerr ( {usb1_esmerr,usb0_esmerr} ),   // Output [ESM-1:0]
  ```
  This is the configuration that matters for the VCS/SIMV_GIT DV environment referenced by this
  project (SIMV_GIT implies VCS simulation, not HAPS emulation), i.e. **both u_usbtop[0] and
  u_usbtop[1] are real, independent instances of the same `usbtop` module** in the DV build.

`usbtop` module parameters at instantiation (SS_VOUT_ALL.v:4504-4515, identical for both `ifdef`
branches): `APBAW=SMPAW, AXIAW=AMAW, AXIIW=4, AXILW=AMLW, AXIUW=AMUW, AXIDW=AMDW, QN=QN, ESM=8,
INTN=1, TKN=1, CN=3`. So **each** usbtop instance has exactly 1 IRQ line, 1 FIQ line, 8 ESM error
bits, 1 token bit, and a 3-wire clock group — this INTN=1/ESM=8 sizing is later critical to the
ESMERR-drop defect (§3.3).

---

## 2. Full interrupt-routing chain: `usb0_irq`/`usb1_irq` → GIC INTID 169/170 (derived, not asserted)

This session had already found that `usb0_irq→169` and `usb1_irq→170`. Below is the **complete
bit-exact RTL derivation** of that mapping, traced across three files, confirming the prior
finding is correct and showing exactly why.

### 2.1 Per-instance IRQ/FIQ/ESM ports — `SS_VOUT_USB.v` (module `usbtop`, the real per-instance top)

`SS_VOUT_USB.v:14474` parameter block declares `ESM = 8` ("esmerr number 8N"); the port
declaration at `SS_VOUT_USB.v:14490`:
```
output   wire  [ ESM       -1:0]  usb_esmerr    , //ESM error Event [1]: axi_chk_err, [0] : apb_chk_err
```
i.e. the port comment **itself documents that only bits [1:0] of the 8-bit usb_esmerr bus are
architecturally meaningful** — bit 0 = APB-interface parity/check error, bit 1 = AXI-interface
parity/check error, bits [7:2] reserved/always-0. Confirmed by the driving assign,
`SS_VOUT_USB.v:14873`:
```
assign   usb_esmerr   = {6'b0, axi_parity_irq, apb_parity_irq} ;
```
`axi_parity_irq` and `apb_parity_irq` are each declared as single-bit wires (`SS_VOUT_USB.v:14870-14871`)
and are driven by real per-transfer-channel AXI/APB parity-checker instances **only when parity
ports are enabled** — see §3.3 for the `` `ifdef AXI4_PARITY_PORT_EN `` / `` `ifdef APB4_PARITY_PORT_EN ``
gating (SS_VOUT_USB.v:15718/15761 for AXI mstpty_errevt→axi_parity_irq; SS_VOUT_USB.v:16010/16016
for APB o_esmerr→apb_parity_irq). When those defines are off, both bits are tied to `1'h0`.

### 2.2 Sub-system aggregation — `SS_VOUT_ALL.v` (module `ss_vout`)

Wire declarations (1-bit each for IRQ/FIQ, 8-bit for ESM), `SS_VOUT_ALL.v:1260-1281`:
```
wire   usb0_irq ; wire usb1_irq ;                    // :1261,:1262
wire   usb0_fiq ; wire usb1_fiq ;                    // :1270,:1271
wire [7:0] usb0_esmerr ; wire [7:0] usb1_esmerr ;     // :1278,:1279
```
Port-level declarations of the `ss_vout` module itself, `SS_VOUT_ALL.v:76-78`:
```
output wire [16-1:0] ss_vout_irq    ,  // IRQ, to cpu interrupt
output wire [16-1:0] ss_vout_fiq    ,  // FIQ, to cpu interrupt
output wire [32-1:0] ss_vout_esmerr ,  // ESMERR Events
```
The aggregation assigns, `SS_VOUT_ALL.v:2256-2269` (exact text):
```verilog
2256  assign   ss_vout_irq          ={ 4'h0
2257                                ,  mipitx_irq    , usb1_irq      , usb0_irq      , pcie_irq
2258                                ,  1'b0          , 1'b0          , mac1_irq      , mac0_irq
2259                                ,  1'b0          , trb_irq       , pkt_irq       , ctl_irq };
2260  // FIQ
2261  assign   ss_vout_fiq          ={ 8'h0
2262                                ,  mipitx_fiq    , usb1_fiq      , usb0_fiq      , pcie_fiq
2263                                ,  1'b0          , 1'b0          , mac1_fiq      , mac0_fiq
2264                                ,  1'b0          , trb_fiq       , pkt_fiq       , ctl_fiq };
2265  // ESMERR
2266  assign   ss_vout_esmerr       ={20'h0
2267                                ,  mipitx_esmerr , usb1_esmerr[0], usb0_esmerr[0], pcie_esmerr[0]
2268                                ,  1'b0          , 1'b0          , mac1_esmerr[0], mac0_esmerr[0]
2269                                ,  1'b0          , trb_esmerr    , pkt_esmerr [0], ctl_esmerr [0]};
```
Bit layout of `ss_vout_irq[15:0]` (MSB→LSB): `[15:12]=0, [11]=mipitx_irq, [10]=usb1_irq,
[9]=usb0_irq, [8]=pcie_irq, [7:6]=0, [5]=mac1_irq, [4]=mac0_irq, [3]=0, [2]=trb_irq, [1]=pkt_irq,
[0]=ctl_irq`. **So `usb0_irq` lands at bit 9 and `usb1_irq` at bit 10 of `ss_vout_irq`.**

### 2.3 SoC-level fan-in to the CPU interrupt bus — `TOP_ALL.v` (module `lan063`)

`cpuirq` is declared as a flat 512-bit bus (`TOP_ALL.v:23991`, `wire [512-1:0] cpuirq`) and fed to
`u_ss_cpu` (which contains the GIC) as its `cpuirq` input port (`TOP_ALL.v:25895`,
`.cpuirq (cpuirq)`, port width parameter `IRQN`, `` `define CPU_IRQN 512 `` at
`SS_CPU_ALL.v:159` — so the port is genuinely 512 bits wide, not the 256 shown in the stale
comment at TOP_ALL.v:25861-25862).

The IRQ half of `cpuirq` (bits [255:0]) is built at `TOP_ALL.v:24763-24773`:
```verilog
24763  assign cpuirq[    224+:      32] = 0          ; //reserved (32)
24764  assign cpuirq[    208+:      16] = ss_qdma_irq; //16
24765  assign cpuirq[    144+:      64] = ss_gcon_irq; //64
24766  assign cpuirq[    128+:      16] = ss_vout_irq; //16      <-- ss_vout's 16 IRQ bits land at cpuirq[143:128]
24767  assign cpuirq[    096+:      32] = ss_vis_irq ; //32
24768  assign cpuirq[    080+:      16] = ss_cpu_irq ; //16
24769  assign cpuirq[    064+:      16] = ss_mem_irq ; //16
24770  assign cpuirq[    032+:      32] = 0          ; //reserved (32)
24771  assign cpuirq[    024+:       8] = ucie0_irq  ; //8
24772  assign cpuirq[    016+:`SE_INTN] = se_irq     ; //8
24773  assign cpuirq[    000+:      16] = gtop_irq   ; //16
```
and the FIQ half (bits [511:256]) mirrors the identical field layout shifted up by 256
(`TOP_ALL.v:24752-24762`), e.g. `assign cpuirq[256+128+:16] = ss_vout_fiq;` (TOP_ALL.v:24755).

So: `ss_vout_irq[9]` (usb0_irq) → `cpuirq[128+9] = cpuirq[137]`; `ss_vout_irq[10]` (usb1_irq) →
`cpuirq[138]`. Symmetrically `ss_vout_fiq[9]/[10]` (usb0_fiq/usb1_fiq) → `cpuirq[393]/[394]`.

Chip-level ESMERR aggregation is a flat concatenation, `TOP_ALL.v:24822`:
```
assign esmerr = {se_esmerr, ss_qdma_esmerr, ss_gcon_esmerr, ss_vout_esmerr, ss_vis_esmerr, ss_cpu_esmerr, ss_mem_esmerr, gtop_esmerr};
```
confirming `ss_vout_esmerr` (with the already-narrowed USB ESM bits, §3.3) is folded directly into
the single chip-wide `esmerr` bus with no further bit selection.

### 2.4 GIC SPI-to-INTID mapping — `SS_CPU_ALL.v` (embedded ARM GIC / "kite" distributor RTL)

`SS_CPU_ALL.v` contains a full ARM GICv3-style distributor implementation (register names
`GICR_CTLR`, `GICR_TYPER`, `GICR_ISENABLER0`, etc., `SS_CPU_ALL.v:40285-40712`) parameterized by
`NUM_SPIS`. The controlling size relationship is stated explicitly at `SS_CPU_ALL.v:41042`:
```
localparam NUM_INT = NUM_SPIS+32;
```
This is the standard ARM GIC convention — INTIDs 0–15 are SGIs, 16–31 are PPIs, and SPI *index* N
(0-based, as delivered on the `spi_i[NUM_SPIS-1:0]` bus, `SS_CPU_ALL.v:41646`) is exposed to
software as **`INTID = N + 32`**. Combined with §2.3's bit placement (`cpuirq` bit index == SPI
index N, since `cpuirq` is what ultimately feeds the GIC's SPI array):
- `usb0_irq` → `cpuirq[137]` → SPI index 137 → **GIC INTID 137+32 = 169** ✓ matches the
  previously-recorded fact.
- `usb1_irq` → `cpuirq[138]` → SPI index 138 → **GIC INTID 170** ✓.

This derivation is internally consistent and independently reproduces the two INTIDs from raw
RTL structure alone (module hierarchy + bit offsets + the GIC's own `NUM_INT=NUM_SPIS+32`
constant), rather than relying on a spec document. (Note: this session did not exhaustively trace
the literal wire from `TOP_ALL.v`'s `cpuirq` port down to `SS_CPU_ALL.v`'s internal `spi_i` net
name — the `cpuirq`→GIC SPI array connection is asserted by the IRQN/NUM_INT parameter agreement
and by ARM GIC convention, and is worth a follow-up `grep` for `spi_i(` / GIC instance port map
inside `SS_CPU_ALL.v` if a future task needs the literal signal-name bridge.)

---

## 3. Interrupt-enable registers, CQ-event mapping, and the two verified RTL defects

### 3.1 `ss_vout_ctl` IRQ/FIQ enable registers (`SS_VOUT_ALL.v`, module `ss_vout_ctl` def'n at :5567)

`ss_vout_ctl` (instantiated as `u_ss_vout_ctl`, SS_VOUT_ALL.v:2296 area) owns two 73-bit
software-visible enable registers, `SS_VOUT_ALL.v:6754-6755`:
```
output reg  [72:0] ss_vout_irqen ,
output reg  [72:0] ss_vout_fiqen ,
```
programmed 8 bits at a time via `wben_regclk` byte-enable strobes at register offsets `'h10`
(IRQ-enable, `SS_VOUT_ALL.v:6987-6996`) and `'h20` (FIQ-enable, `SS_VOUT_ALL.v:7004-7013`), e.g.:
```
if (wben_regclk['h10+0]) ss_vout_irqen [0+:8] <= wdat_regclk [0+:8] ;
...
if (wben_regclk['h10+9]) ss_vout_irqen [72+:1] <= wdat_regclk [72+:1] ;
```
Both registers reset to `73'h0` (all interrupts masked at reset) at `SS_VOUT_ALL.v:6984`/`7001`.
Note these are **73 bits wide**, not 16 — i.e. `ss_vout_irqen`/`ss_vout_fiqen` are a *different,
wider* enable space than the 16-bit `ss_vout_irq`/`ss_vout_fiq` aggregate buses described in §2.2;
they are read back at `SS_VOUT_ALL.v:6911-6912` (`if(cpucsr) regr['h10*8+0+:73] = ss_vout_irqen;`).
A verification engineer probing "is USB0's IRQ masked" needs to identify which of the 73 enable
bits corresponds to `usb0_irq` — this mapping was **not** determined in this pass (the 73-bit
space does not obviously line up 1:1 with the 16-bit `ss_vout_irq` bit positions found in §2.2,
since 73 ≠ 16); flagged here as a specific follow-up for whoever needs to drive/mask this
interrupt from a testbench.

### 3.2 CQ (Central Queue) event mapping (`SS_VOUT_ALL.v` ~2296-2314)

Each of the QN central-queue channels gets a per-source 12-bit event vector via a `generate` loop,
`SS_VOUT_ALL.v` (immediately following the ESMERR assign at :2266-2269):
```verilog
generate
for ( n = 0 ; n < QN ; n = n+1) begin : CQINTEVT_MAP
assign   cqintievt_map[12*n +:12]  = {mipitx_cqintevt[n]
                                   ,  usb1_cqintevt  [n]
                                   ,  usb0_cqintevt  [n]
                                   ,  pcie_cqintevt  [n]
                                   ,  2'b0
                                   ,  mac1_cqintevt  [n]
                                   ,  mac0_cqintevt  [n]
                                   ,  1'b0
                                   ,  trb_cqintevt   [n]
                                   ,  pkt_cqintevt   [n]
                                   ,  ctl_cqintevt   [n]} ;
end
endgenerate
cqint  #(.CQN ( QN ), .EVN ( 12 )
) u_ss_vout_cqint ( .cqinten(cqinten), .cqintievt(cqintievt_map), .cqintmode(cqintmode),
                     .cqintoevt(ss_vout_cqintevt) );
```
This 12-bit-per-channel layout is **bit-position-consistent with the IRQ layout** in §2.2 (same
relative ordering: mipitx, usb1, usb0, pcie, 2 reserved, mac1, mac0, 1 reserved, trb, pkt, ctl) —
i.e. `usb0_cqintevt[n]` occupies bit 9 of `cqintievt_map[12*n+11 : 12*n]`, exactly mirroring
`ss_vout_irq[9]`. This consistency is useful corroboration that the IRQ bit-9 assignment for USB0
is the SoC's genuine, deliberate convention, not a one-off typo.

### 3.3 Defect #1 (verified, real): FIQ concatenation width mismatch is a benign 20→16 truncation, NOT a signal drop

Re-examining the exact text at `SS_VOUT_ALL.v:2261-2264` (§2.2) against the port width
`output wire [16-1:0] ss_vout_fiq` (SS_VOUT_ALL.v:77):

The RHS concatenation is `{8'h0, mipitx_fiq, usb1_fiq, usb0_fiq, pcie_fiq, 1'b0, 1'b0, mac1_fiq,
mac0_fiq, 1'b0, trb_fiq, pkt_fiq, ctl_fiq}` = **8 + 12×1 = 20 bits**, assigned into a **16-bit**
LHS. Verilog continuous-assignment truncation drops the RHS's *most-significant* bits when
RHS width > LHS width. Because the 4 discarded bits are the top 4 bits of the `8'h0` constant
(i.e. still zero), **no real FIQ source bit is actually lost** — the surviving 16 bits are
bit-for-bit `{4'h0, mipitx_fiq, usb1_fiq, usb0_fiq, pcie_fiq, 1'b0, 1'b0, mac1_fiq, mac0_fiq,
1'b0, trb_fiq, pkt_fiq, ctl_fiq}`, i.e. **exactly the same bit-for-bit result as the correctly-sized
IRQ assign at line 2256 (`4'h0` instead of `8'h0`)**. `usb0_fiq`/`usb1_fiq` still land at bits
9/10 of `ss_vout_fiq`, identical to their IRQ counterparts.

**Refinement of the previously-recorded finding**: this line is a genuine **width-mismatch /
lint defect** (a Verilog width-checker such as VCS `-lca` or Spyglass would flag "20-bit
constant-width RHS assigned to 16-bit LHS, 4 bits truncated") and is worth fixing for RTL
hygiene/signoff-clean reasons, but it does **not** functionally drop, misalign, or corrupt any
FIQ source signal in the current SoC config (mipitx/usb1/usb0/pcie/mac1/mac0/trb/pkt/ctl FIQ are
all still correctly present at their expected bit positions). A verification engineer should not
expect to see a missing/miscompared FIQ bit in simulation because of this line; the risk is
purely a code-quality/lint-clean one, and would only become a *real* bug if the block ever grew a
scenario where the extra reserved capacity (bits 19:16, i.e. 4'hF worth of future FIQ sources)
were populated — those would be silently dropped.

### 3.4 Defect #2 (verified, real, functionally meaningful): 7 of 8 ESMERR bits dropped per USB instance — and the 1 real bit that matters is the one that's lost

At `SS_VOUT_ALL.v:2267`: `usb1_esmerr[0]` and `usb0_esmerr[0]` are the only bits of each 8-bit
`usbN_esmerr` bus propagated into `ss_vout_esmerr` — bits `[7:1]` of each are dropped at this
boundary. Counted naively that is indeed "7 of 8 bits dropped," confirming the prior finding
textually. But cross-referencing against the **usbtop-internal** definition of what those 8 bits
actually contain (§2.1, `SS_VOUT_USB.v:14490,14873`) refines the severity:

- Bits `[7:2]` of `usb0_esmerr`/`usb1_esmerr` are **architecturally always 0** at the source
  (`usb_esmerr = {6'b0, axi_parity_irq, apb_parity_irq}` — only 2 of the 8 bits are ever driven
  to anything but constant 0). So 6 of the "7 dropped bits" were already dead weight; dropping
  them costs nothing.
- **Bit `[1]` (`axi_chk_err`/`axi_parity_irq`) is the one real, meaningful signal that this
  boundary silently discards.** Only bit `[0]` (`apb_chk_err`/`apb_parity_irq`) survives into
  `ss_vout_esmerr` and onward into the chip-wide `esmerr` bus (`TOP_ALL.v:24822`). This means:
  **when `` `ifdef AXI4_PARITY_PORT_EN `` is active, a genuine AXI-master-side parity/ECC
  detection event from either USB0 or USB1 (`axi_parity_irq`, driven by the real
  `mstpty_errevt` output of the AXI parity-check IP at `SS_VOUT_USB.v:15718`, gated by
  `` `ifdef AXI4_PARITY_PORT_EN `` at :15761) is generated correctly at the usbtop boundary but
  is architecturally unreachable from the SoC-level ESMERR/FuSa aggregation bus** — it never
  reaches `esmerr`, and therefore never reaches whatever SoC-level FuSa/safety-monitor or GIC-ESM
  interrupt path consumes `esmerr`. Only the APB-side parity error (bit 0) is observable at chip
  level for each USB instance.
- This is a real, reproducible, and probably build-config-dependent gap (it only has teeth when
  `AXI4_PARITY_PORT_EN` is defined for this project's build — when it's undefined, both bits are
  tied 0 at the source per `SS_VOUT_USB.v:15761`/`16016`, so the drop is moot either way). A DV
  engineer targeting FuSa/ESM coverage for USB should check whether `AXI4_PARITY_PORT_EN` is
  defined in this project's compile options (`vcs.opt`/filelist `+define`), and if so, flag that
  AXI-master parity-injection tests on USB0/USB1 (`usb_m_*_pty`/`usb_m_*_inj` ports,
  `SS_VOUT_USB.v` ~15700 area) can never be observed to set a bit in the chip-level `esmerr`,
  only APB-injection tests can.

---

## 4. `ss_vout`-level plumbing around the two USB instances (JTAG mux, clock/token gating)

From `SS_VOUT_ALL.v:2213-2247` — shared 3-way JTAG mux between PCIe/USB1/USB0 (only one core can
own the shared JTAG chain at a time, selected by `jtagsel`):
```verilog
wire   pcie_jtagen = (jtagsel == 2'h3) ;
wire   usb1_jtagen = (jtagsel == 2'h2) ;
wire   usb0_jtagen = (jtagsel == 2'h1) ;
assign ss_vout_jtagtdo = pcie_jtagen & pcie_jtagtdo | usb1_jtagen & usb1_jtagtdo | usb0_jtagen & usb0_jtagtdo ;
// usb1 jtag
assign usb1_jtagtdi = usb1_jtagen & ss_vout_jtagtdi ;
assign usb1_jtagtms = usb1_jtagen & ss_vout_jtagtms ;
assign usb1_jtagrst_n = usb1_jtagen & ss_vout_jtagrst_n ;
// usb0 jtag (same pattern)
```
and independent per-block JTAG clock gating cells `u_usb1_jtagclk` / `u_usb0_jtagclk`
(`ICT_ICG` instances) each enabled only while that block's `jtagen` is asserted
(`SS_VOUT_ALL.v:2236-2238`). `jtagsel==2'h0` de-selects all three (no JTAG owner).

Token (power/clock-domain handshake) bit assignment, `SS_VOUT_ALL.v:2249-2255`:
```
assign {trb_token, pkt_token, ctl_token}   = ss_vout_token[2:0] ;
assign {mac1_token, mac0_token}            = ss_vout_token[4:3] ;
assign  pcie_token                         = ss_vout_token[  5] ;
assign {usb1_token, usb0_token}            = ss_vout_token[7:6] ; // usb0_token=bit6, usb1_token=bit7
assign  mipitx_token                       = ss_vout_token[9:8] ;
```
`usb0_token`/`usb1_token` are the single-bit `TKN=1` tokens fed into each `usbtop` instance's
`.usb_token(...)` port — the same relative ordering (usb1 before usb0 in the concatenation, i.e.
usb0 at the lower/first bit) recurs consistently across token, IRQ, FIQ, ESMERR and CQ-event
mappings — a genuinely uniform SoC-wide convention, not a per-signal accident.

---

## 5. `usbtop` internal structure — `SS_VOUT_USB.v` (17,677 lines; this is the per-instance USB IP top)

`SS_VOUT_USB.v` is confirmed (by its `ESM=8`/`INTN=1`/`TKN=1` parameter block at line 14474,
matching exactly the `usbtop #(...)` instantiation parameters used at `SS_VOUT_ALL.v:4504-4515`
and `:5060`) to be the file containing the real `usbtop` module body that `u_usbtop`/`u_usbtop[1:0]`
instantiate. Content directly confirmed this session from inside it:

- **ESM error generation** (module-boundary output, §2.1/§3.4): `usb_esmerr` port at line 14490,
  driven at line 14873 by `{6'b0, axi_parity_irq, apb_parity_irq}`.
- **AXI4 master-side parity/ECC checker+generator block** (~lines 15690-15761): a full per-channel
  parity check/inject/clear/status interface for every AXI4 channel usbtop drives outward —
  `arready_pty/inj/intclr/intsts`, `rvalid_pty/inj/intclr/intsts`, `rctrl_pty/inj/intclr/intsts`,
  `rdata_ecc/inj/intclr/intsts`, `bvalid_pty/inj/intclr/intsts`, `bctrl_pty/inj/intclr/intsts`
  (check side, driven from the fabric) and `awvalid_pty/awaddr_pty/awctrl_pty`,
  `wvalid_pty/wctrl_pty/wdata_ecc`, `bready_pty`, `arvalid_pty/araddr_pty/arctrl_pty`, `rready_pty`
  (generate side, driven outward) — with a dedicated **`.mstpty_errevt(axi_parity_irq)`** output
  (line 15718) feeding the ESM bit directly. The whole block is gated
  `` `ifdef AXI4_PARITY_PORT_EN `` / `` `else ``, with the `else` branch tying every one of these
  ~19 ports plus `axi_parity_irq` itself to constant 0 (lines 15761 area) when parity is
  compiled out.
- **APB slave-side parity checker** (~lines 15990-16016): checks `i_psel/i_pselchk`,
  `i_penable/i_penablechk`, `i_pwrite/i_pwritechk`, `i_paddr/i_paddrchk`, `i_pprot/i_pprotchk`,
  `i_pstrb/i_pstrbchk`, `i_pwdata/i_pwdatachk` against their odd-parity check bits, with a
  per-event injectable/clearable status interface (`i_inj[ERRW-1:0]`, `i_intclr[ERRW-1:0]`,
  `o_intsts[ERRW-1:0]`, comment "FuSa: per-event ([0]=CTL,[1]=DATA)") collapsing to a single
  **`.o_esmerr(apb_parity_irq)`** output (line 16010, comment "FuSa: esmerr collapsed single line
  (CTL|DATA), level FF to ESM [R1][R5]") — i.e. this one bit is itself already an OR of a CTL-type
  and a DATA-type APB parity fault, so `apb_parity_irq`/`usb_esmerr[0]` conflates two distinct
  fault classes before it ever reaches ss_vout. Same `` `ifdef APB4_PARITY_PORT_EN ``/`` `else ``
  tie-off-to-0 pattern (line 16013-16016) as the AXI block.
- **AXI data-width scaling stage**: immediately after the parity blocks, an `axiwrps_size #(...)`
  instance ("AXI DW Scale (WRITE)", starting ~line 16020) with parameters `IDW=4` (ID width),
  `BAW=32` (buffer addr width), `BLW=8`, `BSW=3`, `CBW=14`, `DW=128` — confirming usbtop's internal
  AXI datapath runs at a **128-bit** internal width before/after the SoC-facing `AXIDW=AMDW`
  parameter width used at the `ss_vout` instantiation boundary (§1.1), i.e. there is a real
  width-conversion stage inside usbtop, not a straight pass-through.

**Not yet extracted this pass** (blocked by remote-relay timeouts, not by absence of content —
see §7 "Session constraints" below): a `grep -n 'module '` pass across `SS_VOUT_USB.v` (17,677
lines) itself was issued to confirm the exact `module usbtop(` line number and enumerate every
sub-module it instantiates by name (UDC/XHCI core, U2/U3 PHY wrapper, register-block instances),
and separate passes were queued against `SS_VOUT_USB_CTRL.v` (185,975 lines — almost certainly the
USB controller/register-map RTL: UDC+XHCI logic and the CSR block) and `SS_VOUT_USB_PHY.v`
(73,485 lines — the U2/U3 PHY digital wrapper). None of these three commands returned a result in
this session (relay stopped responding even to `--status`); the per-instance top-level ports,
parameters, and the three confirmed internal blocks above (ESM/parity generation, AXI DW scaling)
are everything this session was able to pull from inside `usbtop` before the relay stalled.

---

## 6. IP model (`MODEL/`) and macro/PHY behavioral model (`MACRO/`) — directory-level only, content blocked

Both trees were listed successfully early in this session (before the relay stalled):

- `MODEL/` contains: `MODEL_ALL.v` (the flattened IP behavioral model, not yet opened this
  session), `include/` (per-IP model headers — one confirmed subdirectory is `include/ISP/` with
  `ss_vis_ispmodel_define.v`, unrelated to USB), `pufrt_hmc_peri_enc.v.e` (encrypted PUF/RT
  peripheral model), `pvt_def.f` (a filelist, likely for the PVT/thermal model).
- `MACRO/` contains: `MACRO_ALL.v` (flattened macro/PHY behavioral model — this is where this
  session's prior-established `MACRO_ALL.v:1089395` `_tx_vdriver_ana` citation lives, **not
  re-opened/re-verified in this pass** — see below), plus hard-IP macro files
  `CL12812M8RIP.vp`/`CL12812M8RIP_r103.vp` (SRAM compiler macro views), three PLL/ADC `.vp.vcs`
  files (`M31ADC1205TL006G_...`, `M31SOCPLL4508TL006G_...`, `M31SOCPLL4508TL012D_...` — analog
  IP behavioral wrappers for an ADC and two PLL variants), `MACRO_ROM.v`/`MACRO_ROM_SYN.v`,
  `MACRO_SRAM.v`/`MACRO_SRAM_SYN.v` (ROM/SRAM behavioral + synthesis views), and an `include/`
  directory.

**`MACRO_ALL.v:1089395` (`_tx_vdriver_ana`) — NOT independently re-verified this session.** This
citation was already established earlier in this session (per the task brief) but this
extraction pass was not able to re-open `MACRO_ALL.v` before the remote relay stopped responding
(every `remote_exec.py` call issued after the interrupt-routing work in §2-§5, including plain
`--status` checks, has timed out without returning — see §7). Per this report's own standard
("verify these citations directly, don't just re-cite"), this line is deliberately **not**
repeated here as a confirmed fact with invented surrounding detail; it should be re-opened and
re-cited with real surrounding context (what `_tx_vdriver_ana` actually drives, its port list,
what analog TX driver behavior it models — e.g. is it USB U2/U3 HS/SS TX eye-diagram-level drive
strength control, or PCIe/other-protocol shared macro logic) as soon as the relay recovers, before
any downstream agent relies on it as freshly verified.

---

## 7. Session constraints — remote relay contention/stall

Per this task's remote-access instructions: readiness was confirmed at session start
(`python tools/remote/remote_exec.py --status` → `STATUS=READY`, `REMOTE_HOST=host-c`), and roughly
the first dozen commands in §1-§5 above returned normally and are fully real, line-cited RTL
content. Partway through §5 (attempting `grep -n 'module usbtop' SS_VOUT_USB.v` and a companion
`grep` on `SS_CPU_ALL.v` for the literal `spi_i(` GIC port-map connection), every subsequent
`remote_exec.py` invocation — including plain `--status` re-checks — stopped returning within
their timeout window and were moved to background, and none of them produced output even after
extended waiting (multiple 5-minute monitor windows). Per explicit task instruction, `--reconnect`
was not attempted and `remote_relay.py` was not invoked directly; this is reported as a
contention/stall condition for the controller to resolve (e.g. by checking whether the concurrent
USB VIP agent mentioned in the task brief is still holding the relay, or by restarting it) rather
than worked around.

**What this means for completeness of this report**: §§1-4 (module hierarchy, the full
usb0_irq/usb1_irq→GIC INTID 169/170 derivation, both RTL-defect verifications, JTAG/token mux) are
complete and independently re-verified against live RTL text in this session. §5 (usbtop internal
hierarchy) has 3 real, cited findings but is not an exhaustive submodule enumeration. §6 (IP
model/macro model) has only a directory listing — no content was read, and the previously-cited
`MACRO_ALL.v:1089395 _tx_vdriver_ana` fact was deliberately left unrepeated-as-verified rather than
rubber-stamped. A follow-up pass should resume with: (1) `grep -n 'module ' SS_VOUT_USB.v` full
hierarchy, (2) `grep -n 'module ' SS_VOUT_USB_CTRL.v` and `SS_VOUT_USB_PHY.v` (large files — grep
for `^module ` and cap output, don't cat whole files), (3) open `MACRO_ALL.v` around line 1089395
for `_tx_vdriver_ana`'s real port list/behavior, (4) `MODEL_ALL.v` module list and any USB-relevant
behavioral-model content within it, (5) the literal `cpuirq`→GIC `spi_i` signal-name bridge inside
`SS_CPU_ALL.v` flagged in §2.4.

