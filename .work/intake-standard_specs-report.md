# Category 11 Intake: Standard Spec (Interface Spec) — Deep Extraction

Scope: category 11 = standard/interface specifications (protocol-defining documents), as
distinct from VIP docs, DUT RTL, or programming guides. This report (a) corrects the premise
given in the task about which of the 9 named protocols have real local material, and (b)
performs deep, citation-grounded extraction of the four confirmed core USB-family specs.

Extraction method: `pdftotext -layout` on each PDF, then targeted reading of the resulting text
by section number. All line numbers below refer to the `pdftotext -layout` output file, not the
PDF's own page numbering (both are given where useful). Working text dumps are kept at
`D:\DV\Task\DV_Agent_Harness_L5\v50\.work\pdftxt\*.txt` for anyone who wants to re-verify a
citation without re-running pdftotext.

---

## 0. CORRECTION TO TASK PREMISE — broad search results

The task states "only USB-family specs have real local material for this project right now" and
told me to flag protocols with no real material rather than fabricate. I searched broadly under
`D:\DV\Task\` (not just `D:\DV\Task\USB\DOC\`) as instructed. **The premise is wrong for 7 of the
8 non-USB protocols** — real standard-spec PDFs exist elsewhere in the tree, just not under
`USB\DOC`. Only genuine gaps found: none outright — every one of the 9 protocols has at least
one real spec-class document somewhere under `D:\DV\Task\`. This is a materially different
finding than what the task assumed, so I'm reporting it exactly rather than silently going along
with "USB only."

| # | Protocol (as named in task) | Real local material found? | Path(s) |
|---|---|---|---|
| 1 | AMBA | **YES** | `D:\DV\Task\UVM\Spec\AMBA AXI\IHI0022K_amba_axi_protocol_spec.pdf` (ARM AMBA AXI/ACE protocol spec, rev K); `D:\DV\Task\UVM\Spec\AMBA AXI stream\IHI0051A_amba4_axi4_stream_v1_0_protocol_spec.pdf` and `IHI0051B_amba_axi_stream_protocol_spec.pdf` |
| 2 | USB | **YES (primary focus of this report)** | `D:\DV\Task\USB\DOC\usb_20.pdf`, `D:\DV\Task\USB\DOC\USB 3.2 Revision 1.1.pdf`, `D:\DV\Task\USB\DOC\UTMI-PLUS-SPECIFICATION.pdf`, `D:\DV\Task\USB\DOC\extensible-host-controler-interface-usb-xhci.pdf`; also present but not yet deep-extracted: `D:\DV\Task\USB\DOC\DWC_usb31_databook_WM-25380.pdf` (Synopsys USB3.1 controller databook, 5.9MB), `D:\DV\Task\USB\DOC\usb3-phy-interface-pci-express-paper.pdf` (PIPE spec paper) |
| 3 | PCIe | **YES** | `D:\DV\Task\UVM\Spec\PCIE\PCIe-gen-4.pdf`, `D:\DV\Task\UVM\Spec\PCIE\PCIe-gen-5.pdf`. NOTE: `D:\DV\Task\PCIe\` (the directory that mirrors the USB/CAN/MIPI_CSI top-level project layout) is **empty** — the real material lives only under the separate `UVM\Spec\` tree, not in a `PCIe\Spec\` sibling. |
| 4 | MIPI-CSI2 | **YES** | `D:\DV\Task\MIPI_CSI\Spec\mipi_CSI-2_specification_v4-0.pdf`, `D:\DV\Task\MIPI_CSI\Spec\mipi_C-PHY_specification_v2-1.pdf` (also duplicated at `D:\DV\Task\Spec\` and `D:\DV\Task\UVM\Spec\` is absent for CSI but present as `MIPI_CSI_DSI_RX`/`MIPI_CSI_DSI_TX` empty dirs — the real PDFs are in `MIPI_CSI\Spec` and top-level `Spec\`) |
| 5 | MIPI-DSI | **YES** | `D:\DV\Task\MIPI_DSI\Spec\mipi_DSI-2_specification_v2-1.pdf`, `D:\DV\Task\MIPI_DSI\Spec\mipi_D-PHY_specification_v3-5.pdf` (duplicated at `D:\DV\Task\Spec\`) |
| 6 | eMMC/MMC | **YES** | `D:\DV\Task\UVM\Spec\Storage\eMMC\emmc-JESD84-B51 2.pdf` (the real JEDEC eMMC standard). Note: `D:\DV\Task\...\emmc_svt_uvm_user_guide.pdf` (found in several VIP doc trees) is a **VIP user guide, not the eMMC standard** — do not conflate the two if this gets revisited. |
| 7 | SD/SDIO | **YES** | `D:\DV\Task\UVM\Spec\SDIO\113311_Part_E1_SDIO_Speciifcation_Ver2.00_Final_070130.pdf`, `Simplified_SDIO_Card_Spec.pdf`, and under `補充資料\`: `SD_Physical_Layer_Spec.pdf`, `SD_SDIO_specsv1.pdf` |
| 8 | CAN-FD | **YES** | `D:\DV\Task\CAN\Spec\can_fd_spec.pdf`, `can20.pdf`, plus the full ISO 11898 series: `ISO 11898-1 2015.12.15.pdf` (data link layer, CAN FD), `-2` (high-speed PHY), `-3` (low-speed fault-tolerant PHY), `-4` (time-triggered), `-5` (low-power). These are large (up to 61MB) — genuine ISO standard scans, not summaries. |
| 9 | Ethernet | **YES** | `D:\DV\Task\Ethernet\Spec\ieee802.3-2015.pdf` (base Ethernet MAC/PHY standard), `ieee802.3br-2016.pdf` (frame preemption), `ieee802.1Qbu-2016.pdf` (preemption bridging), `ieee802.1Qbv-2015.pdf` (time-aware shaping/TSN), `ieee1588-2008.pdf` (PTP) |

**Bottom line for whoever consumes this**: there is no protocol among the 9 with a zero-material
gap. The actual gap, if the harness wants one flagged, is that **only USB has had deep
section-level extraction done** (this report); the other 8 have real source PDFs sitting
unextracted. I did not deep-extract AMBA/PCIe/MIPI-CSI2/MIPI-DSI/eMMC/SD-SDIO/CAN-FD/Ethernet in
this pass — that was explicitly out of scope per the task instructions ("only USB-family specs
... for this project right now"), and I did not want to silently expand scope. If a future
category-11 pass is meant to cover those, the paths above are the real entry points — flagging
this as a possible follow-up rather than doing it now.

---

## 1. usb_20.pdf — Universal Serial Bus Specification Revision 2.0

Path: `D:\DV\Task\USB\DOC\usb_20.pdf` (extracted text: `.work/pdftxt/usb20.txt`, 32,813 lines)

This is the base USB2 spec: bus protocol, transfer types, chirp/reset/speed detection,
descriptors, and the full device framework. Below is grounded content for exactly what the task
asked for (transfer types + chirp/speed negotiation + descriptors), plus supporting protocol
detail a VIP/DUT model would need.

### 1.1 Chirp / High-speed detection handshake (Section 7.1.7.5 "Reset Signaling", spec p.153-154, extracted lines 8622-8721)

This is the actual USB2 speed-negotiation state machine a verification engineer needs to model
reset/chirp timing checks against. Full numbered protocol as written in the spec:

**Pre-conditions (spec text, line 8656-8686):**
1. Hub checks the attached device is not low-speed (low-speed devices never run the HS detection
   protocol during reset).
2. Hub asserts SE0; the start of SE0 is defined as time **T0**.
3. Device detects SE0 assertion — three sub-cases depending on prior device state:
   - (a) From Suspend: HS detection handshake starts after SE0 detected for ≥2.5µs (`TFILTSE0`).
   - (b) From non-suspended Full-speed: handshake starts after SE0 detected ≥2.5µs and ≤3.0ms
     (`TWTRSTFS`).
   - (c) From non-suspended High-speed: device waits ≥3.0ms and ≤3.125ms (`TWTREV`) before
     reverting to full-speed (remove HS termination, reconnect D+ pull-up), then samples the bus
     100µs–875µs (`TWTRSTHS`) after starting reversion; if SE0 (reset, not suspend) is detected,
     handshake begins.

**High-speed Detection Handshake proper (line 8687-8721):**
4. Device drives **Chirp K** (D+ pull-up stays connected, HS terminations disabled, HS signaling
   current driven onto D-). Must last ≥1.0ms (`TUCH`) and end ≤7.0ms after T0 (`TUCHEND`).
5. Hub must detect the device chirp after seeing Chirp K asserted ≥2.5µs (`TFILT`); if not
   detected, hub continues SE0 until end of reset (device reverts to FS/LS behavior).
6. Within ≤100µs of the bus leaving Chirp K (`TWTDCH`), hub begins an alternating **Chirp K /
   Chirp J** sequence with no Idle states between transitions, continuing until 100–500µs before
   end of Reset (`TDCHSE0`). Each individual chirp is 40–60µs (`TDCHBIT`).
7. After the hub chirp sequence, hub asserts SE0 until end of Reset, then transitions to HS
   Enabled state without causing data-line transitions.
8. Device must detect at minimum the sequence **Chirp K-J-K-J-K-J** (each detected ≥2.5µs,
   `TFILT`) to recognize a valid hub chirp:
   - (a) If detected: within ≤500µs (`TWTHS`), device disconnects D+ pull-up, enables HS
     terminations, enters HS Default state.
   - (b) If NOT detected within 1.0–2.5ms after completing its own chirp (`TWTFS`): device
     reverts to Full-speed Default state and waits for end of Reset.

This is the exact FSM a chirp-sequence checker/scoreboard needs: **device chirp K → hub detects →
hub emits K-J-K-J-K-J → device detects 6-symbol alternation → both commit to HS**, with every
transition timing-bounded (`TUCH`, `TUCHEND`, `TFILT`, `TWTDCH`, `TDCHSE0`, `TDCHBIT`, `TWTHS`,
`TWTFS`). Reset overall duration constraints: hub-port reset ≥10ms (`TDRST`), root-port reset
≥50ms (`TDRSTR`, not necessarily continuous — gaps must be <3ms `TRHRSI` between ≥10ms SE0
bursts), reset recovery time 10ms (`TRSTRCY`) before device/hub must accept new commands (line
8624-8642).

Cross-reference note: `usb_20.pdf` line 8654-8655 explicitly states "Because the downstream
facing port will not be in Transmit state during the Reset Protocol, high-speed Chirp signaling
levels will not provoke disconnect detection" — this connects the chirp levels defined in the DC
level table (line 8358-8366: Chirp J = D+−D− differential ≥+300mV min at target connector; Chirp K
= ≤−300mV) to the disconnect-detect circuit description in 7.1.7.3, useful if a VIP disconnect
checker needs to know it must NOT fire during chirp.

### 1.2 UTMI+ cross-reference for the same chirp sequence (see Section 3, below)

`UTMI-PLUS-SPECIFICATION.pdf` Figure 9 (extracted lines 914-960) gives the PHY-interface-level
view of exactly this same handshake — `OpMode(1:0)` transitions to `10 (Chirp)` during the
handshake window on both host and device sides, `XcvrSelect(1:0)` moves from `01 (FS)` to
`00 (HS)`, and `LINESTATE` shows the literal `SE0 → Device Chirp K → SE0 → Host Chirp KJKJKJ...`
sequence. This is a genuine, useful cross-reference: the spec-level protocol (usb_20.pdf §7.1.7.5)
and the PHY-interface-level signal encoding (UTMI+ §3.1) describe the identical event sequence
from two different abstraction layers — a UTMI-based VIP/DUT model should drive `OpMode=2'b10`
exactly during the window usb_20.pdf bounds with `TUCH`/`TUCHEND`/etc.

### 1.3 Transfer types (Chapter 5, "USB Data Flow Model", spec p.36-53, extracted lines 2837-3806+)

Four transfer types are formally defined (line 2865-2875), each with Data-Format /
Direction / Packet-Size / Bus-Access / Data-Sequence / Error-Handling subsections
(5.5.x=Control, 5.6.x=Isochronous, 5.7.x=Interrupt, 5.8.x=Bulk):

**Control (§5.5, line 2924-3136):**
- Structure: Setup transaction (host→function) + zero-or-more Data transactions (direction per
  Setup) + Status transaction (function→host reporting success/failure) (line 2928-2932).
- Bi-directional message pipe; uses both IN and OUT endpoint of the same endpoint number (§5.5.2).
- Max data payload: FS = 8/16/32/64 bytes (selectable), HS = fixed 64 bytes, LS = fixed 8 bytes
  (§5.5.3, line 2973-2974). Setup packet itself is always exactly 8 bytes.
- Device descriptor's first 8 bytes give `wMaxPacketSize0` (byte offset 7) — host reads this
  before it knows the real max packet size for the default pipe (line 2986-2990).
- Data-stage completion rule: pipe completes on exact expected byte count OR a short/zero-length
  packet (line 2997-3000) — a bus-protocol invariant a scoreboard must check.
- Bus reservation: ≥10% of frame reserved for FS/LS control traffic, ≥20% of microframe for HS
  (§5.5.4, line 3017-3022). Numeric transaction ceilings: <29 FS 8-byte control transfers/frame,
  <4 LS 8-byte/frame, <32 HS 64-byte/microframe (line 3043-3047), with worked bandwidth tables
  (Table 5-1 line 3054-3075 for LS, Table 5-2 line 3107-3134 for FS, e.g. FS 64-byte control
  payload → 120000 B/s max, 30 max transfers/frame, 3% frame bandwidth per transfer).
- HS control endpoints (both directions) **must support the PING flow-control protocol** for OUT
  transactions in the Data and Status stages — but explicitly **not** in the Setup stage (§8.5.1,
  line 11864-11866, see §1.5 below for the PING protocol itself).

**Isochronous (§5.6, line 3208-3401):**
- Semantics: guaranteed bandwidth + bounded latency + guaranteed constant rate, but **no retry on
  error** (line 3213-3215).
- Uni-directional stream pipe (§5.6.2); bidirectional isochronous needs two pipes.
- Max payload: FS = 1023 bytes, HS = 1024 bytes; "high-bandwidth" HS endpoints (>1024B/period)
  need 2 or 3 transactions per microframe (§5.6.3, line 3239-3241, 3365-3369).
- Bus access period: `(2^(bInterval-1)) × F` where F=125µs (HS) or 1ms (FS), bInterval range
  1-16 (line 3356-3361). Default interface settings **must not** include non-zero-payload
  isochronous endpoints (line 3341-3346) — a real device-descriptor-conformance rule.
- No handshake exists at all for isochronous transactions — "the low-level USB protocol does not
  allow handshakes to be returned to the transmitter of an isochronous pipe" (§5.6.5, line
  3384-3397). An isochronous endpoint **never halts** — there's no halt-signaling mechanism for
  this transfer type, which materially differs from control/bulk/interrupt.
- Worked bandwidth tables: Table 5-4 FS (line 3250-3286, e.g. 1023-byte payload → 1023000 B/s,
  1 transfer/frame, 69% frame bandwidth) and Table 5-5 HS (line 3301-3338, e.g. 1024-byte payload
  → 57344000 B/s, 107 transfers/microframe, 14% bandwidth) — real numeric bandwidth-budget
  reference tables a bandwidth/coverage model could cite directly.
- Frame allocation ceiling: ≤90% of a FS frame or ≤80% of a HS microframe for periodic
  (isochronous+interrupt) traffic combined (§5.6.4, line 3352-3354).

**Interrupt (§5.7, line 3402-3427+):**
- Semantics: guaranteed max service period + retry on occasional error (unlike isochronous) (line
  3408-3411).
- Uni-directional stream pipe. Max payload: FS ≤64 bytes, HS ≤1024 bytes (high-bandwidth variant
  also gets 2-3 transactions/microframe like isochronous) (§5.7.3, line 3424-3427).

**Bulk (§5.8, line 3630-3806):**
- Semantics: bandwidth-available, retryable, guaranteed delivery but no bandwidth/latency
  guarantee (line 3634-3637).
- Uni-directional stream pipe; bidirectional needs two pipes.
- Max payload: FS = 8/16/32/64 bytes, HS = fixed 512 bytes; **low-speed devices must not have
  bulk endpoints at all** (§5.8.3, line 3658-3660) — a real descriptor-validity constraint.
- Completion rule identical in shape to control: exact expected count, OR short/zero-length
  packet (line 3679-3684); overrun (larger-than-expected payload) aborts/retires all pending bulk
  IRPs for that endpoint (line 3686-3687).
- Priority ordering: control transfers have priority over bulk; client software cannot assume
  bulk/control ordering (§5.8.4, line 3695, 3709-3710).
- HS bulk OUT endpoints must support the PING protocol (line 3712-3713) — same mechanism as
  control OUT.
- Numeric ceiling: <72 FS 8-byte bulk transfers/frame, <14 HS 512-byte transfers/microframe (line
  3718-3720), with Table 5-9/5-10 worked bandwidth tables (not fully re-transcribed here; same
  format as isochronous tables above).

### 1.4 PING flow control (§8.5.1 "NAK Limiting via Ping Flow Control", spec p.217, extracted line 11856-11910)

Real state-machine-relevant protocol, not just a name: host sends a PING special token; device
responds NAK (no space for a full `wMaxPacketSize` payload — host may retry later, NOT grounds to
retire the transfer) or ACK (space available — host must issue the actual OUT/DATA transaction
next for that endpoint, though other transactions may interleave first). After an OUT/DATA
transaction: device ACK ⇒ room for another wMaxPacketSize payload, host continues OUT/DATA
directly; device NYET ⇒ accepted this payload but no room for the next one, host must return to
PING-probing before sending more data (line 11881-11891). This ACK/NAK/NYET/PING 4-state
handshake is the literal thing a USB2 HS bulk/control-OUT endpoint model or scoreboard has to
implement — not a paraphrase, this is the spec's actual described behavior.

### 1.5 Descriptor structure (Chapter 9.6, spec p.261-271+, extracted lines 14190-14837)

Exact field-level content, since this is what the task called out by name:

**Device Descriptor (Table 9-8, line 14227-14316):** 18 bytes.
`bLength(1)/bDescriptorType(1)/bcdUSB(2)/bDeviceClass(1)/bDeviceSubClass(1)/bDeviceProtocol(1)
/bMaxPacketSize0(1)/idVendor(2)/idProduct(2)/bcdDevice(2)/iManufacturer(1)/iProduct(1)
/iSerialNumber(1)/bNumConfigurations(1)`. Key rules extracted: `bDeviceClass=0` ⇒ each interface
declares its own class independently; `1..0xFE` ⇒ device-aggregate class; `0xFF` ⇒ vendor-specific
(line 14241-14257). `bMaxPacketSize0` valid values are strictly {8,16,32,64}, and **must be 64 if
operating HS** — no other value is legal at HS (line 14211-14213, 14296-14297).
`bNumConfigurations` only counts configs for the *current* operating speed, not both speeds (line
14206-14209) — an easy DUT-model bug if not modeled correctly.

**Device_Qualifier Descriptor (Table 9-9, line 14320-14360):** 10 bytes — describes what the
device WOULD report at its "other" speed if it's HS-capable and currently running at FS (or vice
versa). Fields mirror Device descriptor minus vendor/product/serial-number (those don't change
with speed). A FS-only device (bcdUSB=0200H per its own version but no true HS capability) that
receives a GetDescriptor(device_qualifier) request **must respond with a request error** (line
14357-14358) — this is a real conformance check a compliance-checker test would assert.

**Configuration Descriptor (Table 9-10, line 14389-14468):** 9 bytes.
`bLength/bDescriptorType/wTotalLength(2)/bNumInterfaces(1)/bConfigurationValue(1)
/iConfiguration(1)/bmAttributes(1)/bMaxPower(1)`. `wTotalLength` = combined length of config +
all interface + all endpoint + all class/vendor descriptors returned for that configuration (line
14397-14401) — i.e. GetDescriptor(Configuration) returns the *entire* descriptor tree in one
transfer, not just the 9-byte header. `bmAttributes` bit map: D7=reserved(1), D6=self-powered,
D5=remote-wakeup, D4:0=reserved(0) (line 14418-14425). `bMaxPower` in 2mA units (50 = 100mA).

**Other_Speed_Configuration (Table 9-11, line 14469-14501):** structurally identical to
Configuration descriptor, describes the config that would apply at the device's *other* speed;
host must not request this **unless it has already successfully retrieved device_qualifier
first** (line 14359-14360) — an ordering dependency a sequence/test needs to respect.

**Interface Descriptor (Table 9-12, line 14503-14620):** 9 bytes.
`bLength/bDescriptorType/bInterfaceNumber(1)/bAlternateSetting(1)/bNumEndpoints(1)
/bInterfaceClass(1)/bInterfaceSubClass(1)/bInterfaceProtocol(1)/iInterface(1)`.
`bNumEndpoints` **excludes** endpoint 0 always (line 14530); if an interface uses only EP0,
`bNumEndpoints=0` and no endpoint descriptors follow (line 14527-14528). Alternate settings:
default is always alt-setting 0; `SetInterface()`/`GetInterface()` select/query the active
alternate (line 14513-14515); each alt setting gets its own full interface-descriptor +
endpoint-descriptor block even though `bInterfaceNumber` stays the same across alternates (only
`bAlternateSetting` changes) (line 14521-14525) — descriptor-tree-construction detail a generator
must get right.

**Endpoint Descriptor (Table 9-13, line 14622-14837, cont'd 14669-14768):** 7 bytes.
`bLength/bDescriptorType/bEndpointAddress(1)/bmAttributes(1)/wMaxPacketSize(2)/bInterval(1)`.
- `bEndpointAddress`: bits3:0=endpoint number, bits6:4=reserved(0), bit7=direction
  (0=OUT,1=IN, ignored for control) (line 14641-14649).
- `bmAttributes` bits1:0 = **Transfer Type**: `00=Control, 01=Isochronous, 10=Bulk, 11=Interrupt`
  (line 14661-14665) — the literal encoding a descriptor-parsing checker/monitor must decode.
  For isochronous only, bits3:2=Synchronization Type (`00=None,01=Async,10=Adaptive,
  11=Sync`) and bits5:4=Usage Type (`00=Data,01=Feedback,10=Implicit-feedback-Data,11=Reserved`)
  (line 14671-14683); these bits are reserved/must-be-zero for non-isochronous endpoints.
- `wMaxPacketSize`: bits10:0 = max packet size in bytes; for **HS isochronous/interrupt only**,
  bits12:11 = additional transaction opportunities per microframe (`00=1 total,01=2 total,
  10=3 total,11=Reserved`) (line 14709-14720) — this is the literal high-bandwidth-endpoint
  encoding referenced in §5.6.3/§5.9.
- `bInterval`: units and meaning vary by endpoint type/speed — FS/HS isochronous: exponent form
  `2^(bInterval-1)`, range 1-16; FS/LS interrupt: literal 1-255; HS interrupt: same exponent form,
  range 1-16; **HS bulk/control OUT only**: `bInterval` means max NAK rate (0 = never NAKs,
  otherwise ≤1 NAK per bInterval microframes) (line 14726-14751) — four genuinely different
  semantic meanings packed into the same descriptor byte depending on transfer type/speed/
  direction, a common source of generator/model bugs if treated as one uniform field.

---

## 2. USB 3.2 Revision 1.1.pdf — Universal Serial Bus 3.2 Specification

Path: `D:\DV\Task\USB\DOC\USB 3.2 Revision 1.1.pdf` (extracted text: `.work/pdftxt/usb32.txt`,
30,768 lines). This spec uses "Enhanced SuperSpeed" (eSS) terminology and covers Gen1/Gen2,
x1/x2 lane configurations.

### 2.1 LTSSM — Link Training and Status State Machine (§7.5, spec p.159+, extracted lines 10396-13100+)

This is the exact state machine the task asked for. Overview (line 10398-10429):

**12 LTSSM states, grouped by function (as the spec itself groups them):**
1. **Operational states (4):** `U0` (link active, packets flow or idle), `U1` (low-power, no
   packet transfer, opportunistic PHY power-down), `U2` (deeper low-power, more savings, higher
   exit latency than U1), `U3` (link suspend, most aggressive power saving).
2. **Initialization/training states (4):** `Rx.Detect` (power-on state, detecting Enhanced
   SuperSpeed link partner presence), `Polling` (both partners train Tx/Rx, synchronize, get
   ready for packet transfer), `Recovery` (retrain link — used both when exiting low-power states
   and when a link error is detected in U0, or to switch operation mode), `Hot Reset` (downstream
   port resets upstream port).
3. **Test states (2):** `Loopback` (bit-error test), `Compliance Mode` (transmitter
   voltage/timing compliance test).
4. **Error/disabled states (2):** `eSS.Inactive` (link error state needing software
   intervention), `eSS.Disabled` (Enhanced SuperSpeed connectivity disabled, link may fall back to
   USB2 mode).

**Cross-reference / naming note:** this spec calls the disabled/inactive states `eSS.Disabled` /
`eSS.Inactive` (the "eSS." = Enhanced SuperSpeed prefix). Earlier USB3.0/3.1 spec generations
(not present in this local corpus, so unverifiable here, but worth flagging for anyone
integrating against an older VIP/RTL model) used bare `SS.Disabled`/`SS.Inactive` naming — if a
VIP or DUT built against an older USB3.0 naming convention is combined with this USB 3.2
Rev.1.1 spec text, the state names will not textually match even though the semantics are the
same. Worth checking if this project's VIP source uses `eSS.*` or `SS.*` naming before assuming
they're drop-in identical strings.

**Substates found (via section grep, not all individually deep-read given time budget — flagging
which states have substates and which don't, since this matters for FSM modeling):**
- `Polling` has **8 substates**: `Polling.LFPS, Polling.LFPSPlus, Polling.PortMatch,
  Polling.PortConfig, Polling.RxEQ, Polling.Active, Polling.Configuration, Polling.Idle`
  (§7.5.4.1, line 10883-10899).
- `Recovery` has **3 substates**: `Recovery.Active, Recovery.Configuration, Recovery.Idle`
  (§7.5.10.1, line 10521-10527... actually line 12521-12527).
- `Hot Reset` has **2 substates**: `Hot Reset.Active, Hot Reset.Exit` (§7.5.12.1, line
  12976-12981).
- `eSS.Disabled`, `eSS.Inactive`, `Rx.Detect` each have their own sub-state machines too (§7.5.1,
  §7.5.2, §7.5.3 — headers found at line 10509, 10620, 10710 but not deep-read this pass).
- `Compliance Mode`, `U0`, `U1`, `U2`, `U3` are explicitly flat — "does not contain any substate
  machines" (line 12123, 12163, 12302, e.g.).

**Timeout table — Table 7-12 "LTSSM State Transition Timeouts" (line 10447-10484), fully
transcribed, real numeric values a checker/monitor needs:**
| Timer | From state | Times out to | Value |
|---|---|---|---|
| teSSInactiveQuietTimeout | eSS.Inactive.Quiet | eSS.Inactive.Disconnect.Detect | 12 ms |
| tRxDetectQuietTimeoutDFP | Rx.Detect.Quiet | Rx.Detect.Active | 12–120 ms |
| tRxDetectQuietTimeoutUFP | Rx.Detect.Quiet | Rx.Detect.Active | 12 ms |
| tPollingLFPSTimeout | Polling.LFPS/LFPSPlus | Compliance/Rx.Detect/eSS.Disabled/eSS.Inactive | 360 ms |
| tPollingSCDLFPSTimeout (Gen2/SSP) | Polling.LFPS or LFPSPlus | Polling.RxEQ | 60 µs |
| tPollingLBPMLFPSTimeout (SSP) | PortMatch/PortConfig | Rx.Detect/eSS.Disabled/eSS.Inactive | 12 ms |
| tPollingActiveTimeout | Polling.Active | Rx.Detect/PortMatch/eSS.Disabled/eSS.Inactive | 12 ms (x1) / 24 ms (x2) |
| tPollingConfigurationTimeout | Polling.Configuration | (same targets) | 12 ms (x1) / 24 ms (x2) |
| tPollingIdleTimeout | Polling.Idle | (same targets) | 2 ms |
| tU0RecoveryTimeout | U0 | Recovery | 1 ms |
| tU0LTimeout | U0 | U0 (keepalive LDN/LUP) | 10 µs |
| tNoLFPSResponseTimeout | U1 | eSS.Inactive | 2 ms |
| tU1PingTimeout | U1 | Rx.Detect | 300 ms |
| tNoLFPSResponseTimeout | U2 | eSS.Inactive | (same field, U2 context) |
| tNoLFPSResponseTimeout | U3 | U3 | 300 ms |
| tRecoveryActiveTimeout | Recovery.Active | eSS.Inactive, Rx.Detect | 2 ms |
| tRecoveryConfigurationTimeout | Recovery.Configuration | eSS.Inactive, Rx.Detect | 10 ms |
| tRecoveryIdleTimeout | Recovery.Idle | eSS.Inactive | 12 ms |
| tLoopbackExitTimeout | Loopback.Exit | eSS.Inactive | 6 ms |
| tHotResetActiveTimeout | Hot Reset.Active | eSS.Inactive | 2 ms |
| tHotResetExitTimeout | Hot Reset.Exit | eSS.Inactive | 2 ms |
| tU3WakeupRetryDelay | U3 | U3 | 12 ms |
| tU2RxdetDelay | U2 | U2 | 2 ms |
| tU3RxdetDelay | U3 | U3 | 100 ms |

(Note: the raw PDF table has a couple of misaligned rows in the -layout text extraction around
`PORT_U2_TIMEOUT`/`tU1PingTimeout`/`tNoLFPSResponseTimeout` for U2 — the values for those three
run together in the source table's column layout; I've represented them as best determined from
context but flag this specific spot as worth a direct page-image check (PDF page ~161) before
hard-coding into a checker, rather than trusting the text-extraction alignment blindly.)

**U0 (§7.5.6, spec p.189-190, line 12160-12296) — the "normal operation" state, worth the deepest
read since it's what a verification env spends most cycles in:**
- Two internal timers: `tU0RecoveryTimeout` (1ms, resets on every received link command — if it
  ever expires with zero link commands received, downstream port → Recovery, or if upstream port
  gets neither link command nor packet within 1ms → Recovery) and `tU0LTimeout` (10µs, resets on
  every sent symbol; on expiry downstream port sends a single LDN, upstream sends a single LUP —
  literal keepalive behavior) (line 12174-12187, 12272-12286).
- HP (header packet) response-time budget `tDHPResponse` is **speed/lane-count-dependent**: Gen1x1
  <2540ns, Gen2x1 <1610ns, Gen1x2 <2270ns, Gen2x2 <1355ns (line 12199-2205) — real numeric
  latency budgets for LGOOD_n/LBAD ack timing checks.
- Exit conditions include: successful LGO_U1/U2/U3 entry sequence → U1/U2/U3; 3 consecutive
  failed U3-entry attempts (downstream only) → eSS.Inactive; any Recovery-triggering error (§7.3)
  or TS1 ordered-set detection on any lane → Recovery; directed → Recovery; 4 consecutive
  PENDING_HP_TIMER timeouts → eSS.Inactive (meaning: 3 consecutive Recovery-due-to-
  PENDING_HP_TIMER-timeout round-trips happened first) (line 12217-12247); Warm Reset directed
  (downstream) or detected (upstream) → Rx.Detect; VBUS-off detected (self-powered upstream only)
  → eSS.Disabled (line 12288-12295).
- Port-capability exchange requirement: after entering U0 and completing training, both ports
  must exchange Port Capability LMPs within `tPortConfiguration` time, covering three distinct
  entry paths (direct from Polling, indirect via Hot Reset, or resuming an incomplete negotiation
  from Recovery) — if this doesn't complete in time, downstream port is directed to eSS.Inactive
  and upstream to eSS.Disabled (line 12251-12270). This is a real protocol-completeness
  requirement, not just a link-training detail.

**Recovery (§7.5.10, spec p.195+, line 12512-12820ish):** used for 3 distinct purposes — link
retrain, Hot Reset entry, Loopback entry (line 12514-12515). Key detail: unlike Polling, Recovery
does **not** retrain the receiver equalizer — "the last trained equalizer configurations are
maintained," only TS1/TS2 ordered sets are exchanged to resynchronize and re-exchange link
config (line 12515-12519). `Recovery.Active` requires 8 consecutive identical TS1-or-TS2 ordered
sets received on each negotiated lane before advancing to `Recovery.Configuration` (Gen2 excludes
symbols 14/15, which carry DC-balance-only variation) (line 12581-12589) — an actual bit-exact
exit-handshake rule a link-training checker needs.

**Hot Reset (§7.5.12, spec p.203, line 12963-13030ish):** only a downstream port can initiate.
Sequence: downstream sends ≥16 TS2 OS with Reset bit asserted on each lane →
`Hot Reset.Active` → upstream responds with Reset-bit-asserted TS2 → upstream signals completion
by de-asserting Reset bit in TS2 → downstream responds de-asserted → both exit to
`Hot Reset.Exit` → successful idle-symbol handshake → both return to `U0` (line 12966-12974).
Side effects specified: downstream resets its Link Error Count and PM timers/U1&U2 timeout values
to zero; SSP mode additionally resets Soft Error Count; **port Configuration information is
explicitly preserved (unchanged)** across a Hot Reset (line 12985-12998) — an important
distinction vs. a cold/Warm Reset, worth modeling correctly in a reset-scenario test.

### 2.2 Enhanced SuperSpeed transfer types delta vs USB2 (§4.4, spec p.41-43, line 4069-4168)

**Bulk Streams (§4.4.6.4, line 4069-4158)** — the major USB3-only addition to the bulk transfer
model, not present at all in USB2: extends a standard single-FIFO bulk pipe into a multi-stream
model. Each Stream gets a Stream ID (SID); the "Stream Protocol" is the actual handshake
mechanism (ERDY tagged with CStream ID → host issues IN ACK TPs tagged with that CStream ID →
device returns DPs tagged with CStream ID) (line 4097-4102). Extends host-buffer count from 1 to
**up to 65533** per bulk endpoint (1:1 Stream-ID-to-host-buffer mapping) (line 4111-4113). Either
host or device may initiate/reject a stream selection (line 4120-4126); Device Class spec defines
the out-of-band coordination mechanism for which Stream IDs are valid (line 4115-4118). Critically:
"Since Streams are run over a standard bulk pipe, an error will halt the pipe, stopping all
stream activity" (line 4151-4153) — the same halt semantics as plain USB2 bulk apply at the pipe
level even though there are many logical streams multiplexed onto it.

**Isochronous / Interrupt in USB3.2**: the spec explicitly frames these as extending USB2's
model rather than replacing it — line 4162 references back to USB2 §5.7 directly ("The purpose
and characteristics of interrupt transfers are similar to those defined in USB 2.0").

### 2.3 USB3.2 Descriptors — BOS + SuperSpeed Endpoint Companion (§9.6, spec p.~250-370, line 20321-21717)

USB3.2 adds descriptor types on top of (not replacing) the USB2 device/config/interface/endpoint
descriptors covered in §1.5 above:

- **Binary Device Object Store (BOS)** (§9.6.2, line 20451-21071): a container descriptor holding
  a set of "device capability" sub-descriptors: USB 2.0 Extension (20576), SuperSpeed USB Device
  Capability (20616), Container ID (20769), Platform Descriptor (20809), SuperSpeedPlus USB
  Device Capability (20839), Precision Time Measurement (20981), Configuration Summary
  Descriptor (20996), FWStatus Capability (21038). Not individually deep-read this pass beyond
  their section headers — flagging their existence and location for a future pass.
- **Interface Association Descriptor** (§9.6.4, line 21179) — groups multiple interfaces under
  one function (used e.g. for composite devices); header found, not deep-read.
- **SuperSpeed Endpoint Companion** (§9.6.7, Table 9-28, line 21548-21668) — deep-read, since
  this is the direct USB3 analog of the USB2 endpoint descriptor's transfer-type-dependent
  semantics called out in the task. 6-byte descriptor immediately following every non-EP0
  endpoint descriptor at SuperSpeed+:
  `bLength/bDescriptorType(=SUPERSPEED_USB_ENDPOINT_COMPANION)/bMaxBurst(1)/bmAttributes(1)
  /wBytesPerInterval(2)`.
  - `bMaxBurst`: 0-15, meaning burst of 1-16 packets; **must be 0 for control endpoints** (line
    21572-21584).
  - `bmAttributes` meaning depends on transfer type (mirrors the USB2 pattern of one field, many
    meanings): for **Bulk** endpoints, bits4:0 = MaxStreams (0=no streams, 1-16 encodes
    `2^MaxStreams` streams supported) (line 21586-21595); for **Control/Interrupt**, all 8 bits
    reserved=0 (line 21600-21605); for **Isochronous**, bits1:0=Mult (max packets per service
    interval = `(bMaxBurst+1)×(Mult+1)`, max value 2, must be 0 if bMaxBurst=0), bit7="SSP ISO
    Companion" flag meaning an additional SuperSpeedPlus Isochronous Endpoint Companion descriptor
    immediately follows (line 21607-21638).
  - `wBytesPerInterval`: total bytes per service interval for periodic endpoints only; must be
    zero for control/bulk (line 21645-21667).
- **SuperSpeedPlus Isochronous Endpoint Companion** (§9.6.8, line 21669+): only present/valid
  above Gen1 speed, and only for isochronous endpoints needing >48K bytes/service-interval (line
  21671-21675) — header + intro read, full field table not transcribed this pass.

---

## 3. UTMI-PLUS-SPECIFICATION.pdf — UTMI+ Specification Revision 1.0 (Feb 25, 2004)

Path: `D:\DV\Task\USB\DOC\UTMI-PLUS-SPECIFICATION.pdf` (extracted text: `.work/pdftxt/utmi.txt`,
1,140 lines — much smaller than the other three, this is a PHY-interface pinout/signal-behavior
spec, not a full protocol spec).

This is the ULPI-adjacent parallel PHY-MAC interface spec (UTMI = USB Transceiver Macrocell
Interface; UTMI+ extends it with host/OTG-mode signals). Defines 4 conformance levels (§2,
line 68-86):
- **Level 0**: USB2.0 peripherals only, minimal signal set (line 69).
- **Level 1**: peripherals + host controllers + OTG devices, HS/FS only, adds signals for
  HostDisconnect, long-EOP generation, data-line pulsing, HS keep-alive generation (line 71-76).
- **Level 2**: adds LS support (no hub), introduces `XcvrSelect(1:0)`, LS keep-alive generation,
  `LineState` decoding (line 77-81).
- **Level 3**: adds preamble-packet generation (LS-via-FS-hub support) and multi-port host
  controller support (line 82-85).

**Key interface signals relevant to VIP/DUT PHY modeling (from §2.4.1, line 871-902, and Figure
9, line 914-960):**
- `XcvrSelect(1:0)`: `00b=HS transceiver, 01b=FS transceiver, 10b=LS transceiver, 11b=send/receive
  a LS packet on a FS bus` (line 873-877). At `11b`, the transceiver auto-generates a PRE packet
  at FS speed before the actual LS data (line 878-881) — a real host-mode-only behavior a
  low-speed-via-FS-hub scenario test needs to know about.
- `TermSelect`, `OpMode(1:0)` (0=Normal, 2=Chirp per Figure 9), `TXValid`, `LineState`: the core
  control/status signal group. `LineState` during the chirp sequence literally shows `J → SE0 →
  Device Chirp K → SE0 → Host Chirp KJKJKJ...` (line 935, 949) — this is the PHY-pin-level mirror
  of the usb_20.pdf §7.1.7.5 protocol-level chirp handshake covered in §1.1/1.2 above. **This is
  a genuine, directly useful cross-reference between the two specs**: a UTMI-interface VIP/BFM
  needs to drive exactly these pin transitions at exactly the times usb_20.pdf's chirp state
  machine specifies.
- Section 3.1 "Chirp sequence" (line 914-960) is explicitly scoped to "the case that both the
  peripheral and the host controller are using a UTMI+ level 1 or higher compliant transceiver
  core" — i.e., Level 0 UTMI+ transceivers are not expected to implement chirp signaling at all
  (consistent with Level 0 being peripheral-only / no HS negotiation responsibility implied at
  that level). Worth checking which UTMI+ level any local PHY IP/VIP claims before assuming it
  drives chirp signals.
- Section 3.2 "Suspend/Resume signaling for downstream facing ports" (line 962+) defines a timing
  detail (`T1`, minimum 16 LS bit times) to keep the LS state machine's data path from being cut
  off before a full LS EOP transmits during resume (line 967-975), and a HS-vs-FS
  resume-disambiguation rule: the transceiver must switch to HS mode no later than ¼ LS bit time
  (4 FS bit times) before the end of SE0, and no earlier than SE0-detection-on-LineState, or risk
  ambiguity in resume signaling (line 977-980ish, truncated in this pass — worth a closer re-read
  if a resume/L1-exit scenario needs this specific edge).

---

## 4. extensible-host-controler-interface-usb-xhci.pdf — xHCI Specification

Path: `D:\DV\Task\USB\DOC\extensible-host-controler-interface-usb-xhci.pdf` (extracted text:
`.work/pdftxt/xhci.txt`, 31,654 lines). This is the Host Controller register-level programming
interface spec — distinct in kind from the three link-protocol specs above: it defines the
software/hardware register map, ring-based command/transfer data structures (TRBs), and slot/
endpoint context model that a Host Controller (and its driver) implement. Directly relevant to
anyone modeling or verifying a USB3 host controller DUT or a host-side VIP/BFM.

### 4.1 Operational Register Map (§5.4, Table 5-18, spec p.391, extracted line 19091-19156)

| Offset | Mnemonic | Register | Section |
|---|---|---|---|
| 00h | USBCMD | USB Command | 5.4.1 |
| 04h | USBSTS | USB Status | 5.4.2 |
| 08h | PAGESIZE | Page Size | 5.4.3 |
| 0C-13h | — | RsvdZ | — |
| 14h | DNCTRL | Device Notification Control | 5.4.4 |
| 18h | CRCR | Command Ring Control | 5.4.5 |
| 20-2Fh | — | RsvdZ | — |
| 30h | DCBAAP | Device Context Base Address Array Pointer | 5.4.6 |
| 38h | CONFIG | Configure | 5.4.7 |
| 3C-3FFh | — | RsvdZ | — |
| 400-13FFh | — | Port Register Set 1..MaxPorts (PORTSC/PORTPMSC/PORTLI/PORTHLPMC, grouped consecutive Dwords per port) | 5.4.8-5.4.11 |

Per-port register set (Table 5-19, line 19137-19148): `PORTSC` (offset 0h, Port Status and
Control), `PORTPMSC` (4h, Power Management Status/Control), `PORTLI` (8h, Port Link Info),
`PORTHLPMC` (Ch, Hardware LPM Control). `MaxPorts` comes from the `HCSPARAMS1` capability
register. Note on virtualization: when Operational Registers are exposed via a Virtual Function
(VF), they're emulated by the VMM, which has discretion over write effects/read values (line
19150-19155) — relevant if the project's environment ever needs SR-IOV/VF modeling.

`USBCMD` (§5.4.1, line 19157-19180+): 32-bit, RO/RW mixed, default 0. Bit 0 = **Run/Stop (R/S)**
— `1`=Run (xHC executes its schedule as long as this stays 1), `0`=Stop (line 19178-19180). Other
named bits visible in the register-bitfield diagram but not individually transcribed this pass:
`INTE, HSEE, LHCRST, CSS, CRS, EWE, EU3S, CME, ETE, TSCEN, VTIOEN` (from the Figure 5-14 bit
layout, line 19169-19172) — flagging their existence/positions for a future deeper pass rather
than guessing their semantics without reading each one.

### 4.2 TRB (Transfer Request Block) structure (§4.11, spec p.208-209, extracted line 10062-10151)

TRBs are the fundamental data structure moved through Command/Transfer/Event rings. Template:
3 components — **Parameter**, **Status**, **Control** (32 bits each, 3 Dwords, with the TRB Type
field always in Control bits 10-15 and the Cycle bit always in Control bit 0) — total 4 Dwords
(16 bytes) per TRB (line 10067-10102). Producer/consumer roles differ by ring type: for
Command/Transfer rings, **system software produces, xHC consumes** (all fields read-only to the
xHC once written); for the Event ring, **the xHC produces, system software consumes** (line
10080-10086, 10131-10141). Real ordering constraint worth noting for a BFM: "if all 4 Dwords of a
TRB are not written as an atomic memory operation, the Parameter and Status components... shall
be initialized prior to writing the Control Component" — writing Control (which carries the Cycle
bit that makes the TRB visible to the xHC) must happen last (line 10110-10113). Bus-mastering
implementation note: xHC is architected around ≥16-byte atomic TRB reads (larger burst reads for
efficiency are allowed, e.g. fetching 4 TRBs in one 64B transaction) (line 10122-10129).

**TRB Type Definitions (Table 6-91, spec p.511-512, extracted line 25248-25340)** — the full
enumeration, with which ring(s) each ID is legal on:
| ID | Name | Legal on |
|---|---|---|
| 0 | Reserved | — |
| 1 | Normal | Transfer |
| 2 | Setup Stage | Transfer |
| 3 | Data Stage | Transfer |
| 4 | Status Stage | Transfer |
| 5 | Isoch | Transfer |
| 6 | Link | Command + Transfer |
| 7 | Event Data | Command + Transfer |
| 8 | No-Op | Command + Transfer |
| 9 | Enable Slot Command | Command |
| 10 | Disable Slot Command | Command |
| 11 | Address Device Command | Command |
| 12 | Configure Endpoint Command | Command |
| 13 | Evaluate Context Command | Command |
| 14 | Reset Endpoint Command | Command |
| 15 | Stop Endpoint Command | Command |
| 16 | Set TR Dequeue Pointer Command | Command |
| 17 | Reset Device Command | Command |
| 18 | Force Event Command (optional, virtualization only) | Command |
| 19 | Negotiate Bandwidth Command (optional) | Command |
| 20 | Set Latency Tolerance Value Command (optional) | Command |
| 21 | Get Port Bandwidth Command (optional) | Command |
| 22 | Force Header Command | Command |
| 23 | No Op Command | Command |
| 24 | Get Extended Property Command (optional) | Command |
| 25 | Set Extended Property Command (optional) | Command |
| 26-31 | Reserved | — |
| 32 | Transfer Event | Event |
| 33 | Command Completion Event | Event |
| 34 | Port Status Change Event | Event |
| 35 | Bandwidth Request Event (optional) | Event |
| 36 | Doorbell Event (optional, virtualization only) | Event |
| 37 | Host Controller Event | Event |
| 38 | Device Notification Event | Event |
| 39 | MFINDEX Wrap Event | Event |
| 40-47 | Reserved | — |
| 48-63 | Vendor Defined | Optional on any ring |

Enforcement rule stated explicitly: any TRB type found on a ring where it isn't "Allowed" per this
table generates an error completion — Command Ring → Command Completion Event with Completion
Code=TRB Error; Transfer Ring → Transfer Event with Completion Code=TRB Error, both carrying the
address of the offending TRB (line 25342-25356) — this is a directly checkable DUT-conformance
rule for an xHCI-model scoreboard (illegal-TRB-type injection test).

---

## Cross-references and contradictions noticed across sources

1. **Chirp handshake, protocol-layer vs. PHY-interface-layer**: `usb_20.pdf` §7.1.7.5 (bus-level
   timing FSM) and `UTMI-PLUS-SPECIFICATION.pdf` §3.1/Figure 9 (PHY-pin-level signal encoding)
   describe the *same* event sequence at two different abstraction layers with fully consistent
   timing — not a contradiction, but a genuine, useful pairing: a UTMI-based chirp checker/BFM
   needs both documents together (protocol timing bounds from usb_20.pdf, exact `OpMode`/
   `XcvrSelect`/`LineState` pin encodings from UTMI+).
2. **LTSSM naming drift risk**: USB 3.2 Rev 1.1 uses `eSS.Disabled`/`eSS.Inactive` naming; no
   USB3.0/3.1-era spec text exists locally to cross-check whether this project's VIP/RTL uses the
   older bare `SS.*` naming — flagged as a naming-consistency risk to check against actual VIP
   source, not confirmed as an actual contradiction (no older-spec text available locally to
   compare against).
3. **eMMC material double-check**: multiple VIP-doc trees contain `emmc_svt_uvm_user_guide.pdf`
   which is a **Synopsys VIP user guide**, not the eMMC/JEDEC standard itself. The actual JEDEC
   standard (`emmc-JESD84-B51 2.pdf`) lives only under `D:\DV\Task\UVM\Spec\Storage\eMMC\`. Do not
   let a future pass conflate "VIP user guide found" with "standard spec found" for eMMC — they
   are different document classes at different paths.
4. **PCIe/MIPI-CSI project-directory mismatch**: the project convention elsewhere (USB, CAN,
   Ethernet, MIPI_DSI) puts real spec PDFs directly under `<Protocol>\Spec\`. For PCIe, the
   parallel `D:\DV\Task\PCIe\` directory exists but is **completely empty** — the real PCIe Gen4/
   Gen5 spec PDFs instead live under the separate `D:\DV\Task\UVM\Spec\PCIE\` tree. Anyone writing
   a generic "look under `<Protocol>\Spec\`" convention into tooling should special-case PCIe (and
   probably AMBA, which similarly has no material under `D:\DV\Task\AMBA\` beyond an empty
   `examples\` dir — its real material is also only under `UVM\Spec\`).
5. **48+ real, unopened PDFs remain**: this pass intentionally limited deep extraction to the 4
   named-in-task-scope USB core docs. `DWC_usb31_databook_WM-25380.pdf` (Synopsys USB3.1
   controller databook — likely contains a register map for an actual DUT-class controller IP,
   complementary to the xHCI host-side spec above) and `usb3-phy-interface-pci-express-paper.pdf`
   (PIPE interface spec paper, relevant to PHY-MAC interfacing analogous to UTMI+ but for
   SuperSpeed) are both real, both under `USB\DOC\`, and both still unextracted — flagging as the
   most likely next USB-family targets if this category-11 intake continues.

---

## Files produced by this extraction

- Report (this file): `D:\DV\Task\DV_Agent_Harness_L5\v50\.work\intake-standard_specs-report.md`
- Raw `pdftotext -layout` dumps (kept for citation re-verification):
  - `D:\DV\Task\DV_Agent_Harness_L5\v50\.work\pdftxt\usb20.txt` (32,813 lines)
  - `D:\DV\Task\DV_Agent_Harness_L5\v50\.work\pdftxt\usb32.txt` (30,768 lines)
  - `D:\DV\Task\DV_Agent_Harness_L5\v50\.work\pdftxt\utmi.txt` (1,140 lines)
  - `D:\DV\Task\DV_Agent_Harness_L5\v50\.work\pdftxt\xhci.txt` (31,654 lines)
