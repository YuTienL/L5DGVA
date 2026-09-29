# Category 6 Intake: Programming Guide (Device-Mode Bring-Up Sequence)

**Source examined (real material, full read of relevant chapters, not an index):**
`D:\DV\Task\USB\DOC\IP\DWC_usb31_programming.txt` (35,383 lines; plain-text extraction of
`DWC_usb31_programming.pdf`, Synopsys DesignWare Cores Enhanced SuperSpeed USB 3.1 Controller
**Programming Guide**, Version 2.10a, January 2024). Page numbers below are the "SolvNetPlus NNN"
folio numbers embedded in the text, which correspond 1:1 to the printed/PDF page numbers — cited
as `p.NNN` — plus the text file's own line numbers (`txt:NNNN`) for exact re-location in the
.txt sibling file used for extraction. The companion `.pdf` was not re-opened because the `.txt`
carries the same running headers/folios and is faster to grep/cite precisely; if a reviewer wants
the original layout, open `DWC_usb31_programming.pdf` at the same page number.

This report is the deep extraction for the **register-programming SEQUENCE for device-mode
bring-up** (reset -> clock/refclk-adjacent setup -> endpoint configuration via DEPCFG -> event
buffer setup -> connect), precise enough to check the harness's existing BFM/pattern findings
against real documented text.

---

## 1. Where the sequence lives in the document

- Chapter 4, "Programming DWC_usb31 in Device Mode" starts at `p.559` (`txt:28237`).
- Section **4.1 "Initializing Registers"** at `p.560` (`txt:28241`) enumerates the seven
  lifecycle events software must handle, in order:
  1. Power-On or Soft Reset
  2. USB Reset Event
  3. Connect Done Event
  4. SetAddress Device Request
  5. SetConfiguration Device Request
  6. Disconnect Event
  7. Device-Initiated Disconnect and Reconnect
- Immediately under that list (`p.560`, `txt:28255`):
  > "Note: After vcc_reset_n de-assertion, software should wait for at least 10 bus_clk cycles
  > before accessing any register in the controller."
  This is a real hardware precondition that precedes even DCTL.CSftRst and is not represented in
  any BFM pattern reviewed so far (worth flagging as a possible 3rd gap, though it's a timing
  wait rather than a register write).

## 2. Section 4.1.1 "Device Power-On or Soft Reset" (`p.559-561`, `txt:28259-28361`) — THE canonical bring-up table

This is **Table 4-1 "Power-On or Soft Reset Register Initialization"**. The guide's own ordering
rule, quoted verbatim (`txt:28265-28266`):

> "When the controller is first powered on, software initializes the following registers. **The
> order of operations is not important, except for the first and last steps (DCTL.CSftRst=1 and
> DCTL.RunStop=1)**"

This sentence is the load-bearing citation for both harness defects:

### Defect 1 confirmed: DCTL.CSftRst=1 must be the FIRST step
Table 4-1's first row (`txt:28272-28273`):

> **DCTL** — "Set the CSftRst field to `1' and wait for a read to return `0'. This resets the
> device controller."

This is listed first in the table and is explicitly called out (along with RunStop) as one of
the two steps whose *order* is mandatory ("except for the first and last steps"). So: **any BFM
init pattern that does not issue DCTL.CSftRst=1 as the first act of device-mode bring-up
contradicts the documented sequence exactly as stated** — this is not an inferred convention, it
is the literal ordering rule in the guide. The wait-for-read-returns-0 polling requirement is
also explicit (self-clearing bit, see register-level detail in §5 below).

### Defect 2 confirmed: DALEPENA must come AFTER endpoint configuration, immediately before DCTL.RunStop
Table 4-1's rows, in the guide's own presentation order (`txt:28268-28361`), for physical
endpoints 0 and 1 (the default control endpoint pair) are, condensed with citations:

1. `txt:28272` **DCTL.CSftRst=1**, poll for 0. (first step, mandatory position)
2. `txt:28275-28316` GSBUSCFG0/1, GTXTHRCFG/GRXTHRCFG, USB31_VER_NUMBER (read Synopsys ID),
   GUID, GUSB2PHYCFG (incl. `USBTrdTim`, `FSIntf`, `PHYIf`, `TOUTCal`, `eUSB2OPMODE`, and the
   explicit note that `GUSB2PHYCFG[15] ULPIAutoRes` **must be written 0** in device mode "because
   the PHY must not be enabled for auto-resume in device mode" — a real init-time PHY
   requirement), GTXFIFOSIZn, GRXFIFOSIZ0, GCTL (scaledown/RAM clock select/clock gating
   overrides).
3. `txt:28309-28313` **GEVNTADRn / GEVNTSIZn / GEVNTCOUNTn** — "Depending on the number of
   interrupts allocated, program the Event Buffer Address and Size registers to point to the
   Event Buffer locations in system memory, the sizes of the buffers, and unmask the interrupt."
   with the warning: "USB operation stops if the Event Buffer memory is insufficient, because
   the controller stops receiving/transmitting packets." (Event buffer setup precedes
   endpoint-command issuance in the table's presentation, consistent with §4.2.2's own 4-step
   event-buffer recipe, see §3 below.)
4. `txt:28318-28320` **DCFG** — program device speed (`DevSpd`); note: "If
   HWPARAMS3.DWC_USB31_SSPHY_INTERFACE is zero, then program the DCFG.DevSpd to USB 2.0-only
   (HS/FS) speeds."
5. `txt:28322-28323` **DEVTEN** — "At a minimum, enable USB Reset, Connection Done, and USB/Link
   State Change events." (register-level bit identities in §5.4 below: bit1=USBRSTEVTEN,
   bit2=CONNECTDONEEVTEN, bit3=ULSTCNGEN → minimum recommended value = 0x0E.)
6. `txt:28325-28327` **DEPCMD0 — Issue DEPSTARTCFG** with `DEPCMD0.XferRscIdx=0`, `CmdIOC=0`, "to
   initialize the transfer resource allocation. Poll CmdAct for completion." (This must precede
   any DEPCFG — DEPSTARTCFG is command 9 in the Physical-Endpoint command set, detailed further
   in §4/ Command 9 notes: "After power-on-reset with XferRscIdx=0 before starting to configure
   Endpoints 0 and 1. CmdIOC must be set to '0'... because Endpoint 0 is not yet configured with
   a valid interrupt number." `p.549`, `txt:27826-27829`.)
7. `txt:28329-28337` **Issue a DEPCFG command for physical endpoints 0 & 1**, with: USB Endpoint
   Number = 0 or 1, `FIFONum=0`, `XferNRdyEn=1` and `XferCmplEn=1`, `MaxPacketSize=512`,
   `BurstSize=0`, `EPType=2'b00 (Control)`. Explicit ordering note: **"The command has to be
   issued for EP0 first, followed by EP1."**
8. `txt:28339-28341` **Issue a DEPXFERCFG command for physical endpoints 0 & 1**, with
   `DEPCMDPAR0_0/1 = 1`, poll CmdAct. Again: **"The command has to be issued for EP0 first,
   followed by EP1."**
9. `txt:28350-28355` **DEPCMD0** — prepare a Setup-packet buffer, initialize a setup TRB, issue
   **DEPSTRTXFER** for physical endpoint 0 pointing at the setup TRB. Poll CmdAct. Note: "The
   controller attempts to fetch the setup TRB through the requester interface after this command
   completes."
10. `txt:28357` **DALEPENA — "Enable physical endpoints 0 & 1 by writing 0x3 to this register."**
    This is step 10 of 11 — it comes strictly **after** DEPSTARTCFG, DEPCFG(EP0),
    DEPCFG(EP1), DEPXFERCFG(EP0), DEPXFERCFG(EP1), and the DEPSTRTXFER-for-setup-TRB step.
11. `txt:28359-28361` **DCTL.RunStop = 1** — "Set DCTL.RunStop to `1' to allow the device to
    attach to the host. At this point, the device is ready to receive SOF packets, respond to
    control transfers on control endpoint 0, and generate events." This is the documented *last*
    step, matching the "except for the first and last steps" ordering rule from `txt:28266`.

**So the documented DALEPENA position is precise**: it is item 10 of the 11-item sequence —
after `DEPSTARTCFG` + `DEPCFG(EP0)` + `DEPCFG(EP1)` + `DEPXFERCFG(EP0)` + `DEPXFERCFG(EP1)` +
setup-TRB `DEPSTRTXFER`, and immediately before `DCTL.RunStop=1`. **Any BFM pattern that writes
DALEPENA before at least the DEPCFG commands for EP0/EP1 have been issued (and, more strictly,
before DEPSTARTCFG/DEPXFERCFG/DEPSTRTXFER have completed) contradicts this table exactly.** The
harness's finding of "3 patterns write DALEPENA before any endpoint is configured" is the more
severe version of this violation (writing DALEPENA with zero DEPCFG issued at all) and is
unambiguously wrong per this table.

Cross-check register-level confirmation of *why* DALEPENA-before-DEPCFG is wrong: the DALEPENA
register description itself (`p.356`, `txt:19262-19282`, Table 1-107) states:

> "USB Active Endpoints (USBActEP)... The entity programming this register must set bits 0 and 1
> because they enable control endpoints that map to physical endpoint (resources) **after
> USBReset**. Hardware clears these bits for all endpoints (other than EP0-OUT and EP0-IN) after
> detecting a USB reset event."

This independently corroborates that DALEPENA is meant to be programmed once the endpoint↔physical
resource mapping already exists (i.e., after DEPCFG), not as a substitute for it.

Immediately after Table 4-1 (`txt:28363-28370`), the guide states the two events software must
then wait for:

> "1. Wait for a DEVT.USBReset event... perform the steps listed in 'Initialization on USB
> Reset'... 2. Wait for a DEVT.ConnectionDone event... read the DSTS register to get the
> connection speed... perform the steps listed in 'Initialization on Connect Done'."

## 3. Section 4.2.2 "Event Buffers" (`p.567`, `txt:28627-28658`) — the canonical 4-step event-buffer recipe

This is the more detailed, order-explicit recipe referenced implicitly by Table 4-1's GEVNTADRn
row. Quoted in full (`txt:28631-28640`):

> "To configure an Event Buffer, the software performs the following steps:
> 1. Sets up an empty buffer in system memory.
> 2. Writes the address of the beginning of the buffer into GEVNTADRn. This address must be
>    aligned to the Event Buffer size.
> 3. Writes the size of the buffer and interrupt mask into GEVNTSIZn. Depending on your system
>    interrupt latency, enough Event Buffer space must be allocated to avoid lost interrupts or
>    reduced performance.
> 4. Write a 0 into the GEVNTCOUNTn register. **This must be the last step, as it enables the
>    Event Buffer.**"

Follow-on constraint (`txt:28641`): "After the Event Buffer has been configured, software must
not change the size or address." And (`txt:28654-28658`): event buffer is a circular buffer —
first event goes to `GEVNTADRn`, subsequent events at `+4`, wrapping at `GEVNTADRn + GEVNTSIZn`.

**This gives a THIRD checkable ordering rule** distinct from the two the harness already found:
`GEVNTADRn` and `GEVNTSIZn` must be written before `GEVNTCOUNTn` is written to 0 — writing
`GEVNTCOUNTn=0` is explicitly "the last step" of event-buffer bring-up because it is the enable.
A BFM pattern that zeroes GEVNTCOUNTn before (or without) programming GEVNTADRn/GEVNTSIZn would
be violating this documented order, worth checking as a possible 3rd defect class alongside the
two already found. Register-level detail (`p.251`, `txt:13756-13762`, GEVNTCOUNT description)
corroborates: "During initialization, software must initialize the count by writing 0 to the
Event Count field."

Register-level detail for the other two (both "Exists: Always" / initialize-once, do-not-touch
afterward):
- `GEVNTADRLO/HI` (`p.249-250`, `txt:13628-13632`, `13664-13668`): "Software must initialize this
  address once during power-on initialization. Software must not change the value of this
  register after it is initialized. ... The lower n bits of the address must be
  GEVNTSIZn.EVNTSiz-aligned." Offsets: `GEVNTADRLO(#n) = 0xc400 + i*0x10`,
  `GEVNTADRHI(#n) = 0xc404 + i*0x10`.
- `GEVNTSIZ(#n)` (`p.251`, `txt:13699-13746`, offset `0xc408 + i*0x10`): bit 31
  `EVNTINTRPTMASK` ("When set to '1', prevents the interrupt from being generated. However, even
  when the mask is set, the events will be written to the Event Buffer."), bits [15:0]
  `EVENTSIZ` ("must be a multiple of four... minimum size of the event buffer is 32 bytes").
- `GEVNTCOUNT(#n)` (`p.251`, `txt:13753-13769`, offset `0xc40c + i*0x10`): count of valid bytes;
  software writes back the number of bytes processed after each interrupt.

## 4. Section 4.1.2 "Initialization on USB Reset" (`p.562`, `txt:28372-28395`) — Table 4-2

Steps on `DEVT.USBReset`:
- `DEPCMD0`: if a control transfer is in progress, complete it and get to "Setup a
  Control-Setup TRB / Start Transfer" state.
- `DEPCMDn`: issue `DEPENDXFER` for any active transfers (except default EP0).
- `DEPCMDn`: issue `DEPCSTALL` (ClearStall) for any endpoint in STALL mode (excluding control
  endpoints).
- `DCFG`: set `DevAddr` to 0.
- Special note: "The default control endpoint is not affected by USB Reset... Resources can only
  be assigned to the default control endpoint once after a power-on or soft reset." (i.e., EP0/1
  DEPCFG is NOT reissued on every USB Reset — only on power-on/soft-reset.)

## 5. Section 4.1.3 "Initialization on Connect Done" (`p.562`, `txt:28397-28419`) — Table 4-3

Steps on `DEVT.ConnectionDone`:
- `DSTS`: read to obtain connection speed.
- `GCTL`: "Program the RAMClkSel field to select the correct clock for the RAM clock domain.
  This field is reset to 0 after USB reset, so it must be reprogrammed each time on Connect
  Done." **This is a real per-connect-done register write.**
- `DEPCMD0/DEPCMD1`: issue **DEPCFG with Config Action = "Modify"** for physical EP0 & EP1 using
  the same characteristics as power-on, but updating `MaxPacketSize` to 512 (SS) / 64 (HS) /
  8-16-32-64 (FS) / 8 (LS).
- `GTXFIFOSIZn` (optional): may re-allocate TxFIFO sizes based on new EP0 IN MaxPacketSize.

**Cross-reference / contradiction worth flagging**: the GCTL.RAMCLKSEL register-level
description (`p.121`, `txt:6915-6928`, Table 1-23) says:

> "The ram_clk_out must be connected back to ram_clk_in for this feature to work. **Only a value
> of 0 should be used for this register field.**... Note: In both host and device modes, this
> register field setting should not be modified."

This directly conflicts in tone with the Connect-Done table's instruction to "reprogram... each
time on Connect Done" — the register page says not to modify it away from 0, while the
programming-flow page says to actively reprogram it on every Connect Done event. In practice
this is likely benign (reprogram to the *same* value, 0, every time — "reprogram" doesn't imply
"change the value," and the field resets to 0 on USB Reset so rewriting 0 is a no-op restore),
but it is a genuine textual tension between the register reference chapter and the programming
flow chapter that a verification engineer should be aware of when writing a checker: don't flag
"GCTL written with the same value repeatedly" as a bug for this specific field.

## 6. Sections 4.1.4 / 4.1.5 / 4.1.6 / 4.1.7 — later lifecycle (for completeness, not core bring-up)

- **4.1.4 SetAddress** (`p.563`, `txt:28421-28437`, Table 4-4): program `DCFG.DevAddr`; after
  `XferNotReady(Status)` event, ack status stage via `DEPSTRTXFER` on DEPCMD1 pointing to a
  Status TRB — "This step must be done after the DCFG register is programmed with the new device
  address."
- **4.1.5 SetConfiguration/SetInterface** (`p.563-564`, `txt:28439-28485`, Table 4-5): the
  sequence here is: **DALEPENA=0x3 first (disable all but EP0)** → `DEPENDXFER` for active
  transfers → `DEPCFG(Modify)` EP1 → `DEPSTARTCFG` with `XferRscIdx=2` → `DEPCFG(Initialize)` for
  each new-config endpoint → `DEPXFERCFG` for each new-config endpoint → optional
  `GTXFIFOSIZn` → **DALEPENA enable the new active endpoints** → ack Status stage via
  `DEPSTRTXFER` on DEPCMD1. Note the important asymmetry vs. power-on: here DALEPENA is written
  *twice* — once early (to disable, value 0x3) and once late (to enable the new set) — so a
  "DALEPENA write before DEPCFG" check must be scoped to the **power-on bring-up** sequence
  specifically (Table 4-1), not applied blindly to the SetConfiguration flow, where an
  early *disabling* DALEPENA write is correct and documented.
- **4.1.6 Alternate SetInterface** (`p.564`, `txt:28487-28510`, Table 4-6): reconfigure existing
  endpoints without restarting from scratch; `DEPCFG(Initialize)` per changing endpoint (resets
  seq number to 0) then `DALEPENA` written with the full enabled set (changing + unchanged).
- **4.1.7 Disconnect Event** (`p.564`, `txt:28512-28517`): "the application must set DCTL[8:5] to
  5. Other than this, the controller does not require any initialization. Because the
  DCTL.RunStop bit is still '1', the device attempts to reconnect."

## 7. DEPCFG command parameter detail (Section 3.2.2.1, `p.541-544`, `txt:27332-27503`, Table 3-3)

Full field map for the DEPCFG command used in steps 7 (power-on) and elsewhere:
- **Parameter 2** (31:0): endpoint state, used only when Config Action=1 (Restore); otherwise
  reserved.
- **Parameter 1**:
  - bit 31 `FIFO-based` (isochronous FIFO-mode streams only)
  - bits 29:25 `USB Endpoint Number`: bits[29:26]=endpoint number, bit[25]=direction
    (0=OUT, 1=IN). Explicit rule: **"Physical endpoint 0 (EP0) must be allocated for control
    endpoint 0 OUT. Physical endpoint 1 (EP1) must be allocated for control endpoint 0 IN."**
  - bit 24 `StrmCap` (stream-capable)
  - bits 23:16 `bInterval_m1` (bInterval - 1, valid 0-13)
  - bit 15 EBC-related, bit 14 EBC enable, etc.
- **Parameter 0**:
  - bit 31/30: HWO writeback control for TRB
  - bits 13:8 `DEPEVTEN` (per-endpoint event enables): bit13 StreamEvtEn, bit10 `XferNRdyEn`,
    bit9 `XferInProgEn`, bit8 `XferCmplEn`.
  - `IntrNum`: "Indicates interrupt/Event Buffer number on which endpoint related interrupts for
    this endpoint are generated. If multiple Interrupter configuration is not selected, this
    must be 0."
  - **Config Action** (2 bits): `0 = Initialize` (first-time config; resets seq number and flow
    control; DEPCMDPAR2 ignored), `1 = Restore` (post-hibernation, restores seq num/flow control
    from DEPCMDPAR2), `2 = Modify` (change event enables/IntrNum/MPS without resetting
    sequence/flow-control state; DEPCMDPAR2 ignored).
  - `BrstSiz` (bits, burst length encoding 0=1 up to 15=16), `FIFONum` ("For control endpoints,
    the FIFONum value in the OUT direction must be programmed to the same value as the IN
    direction."), `MPS` (Maximum Packet Size, up to 1024B for USB 3.1), `EPType` (2 bits:
    00=Control, 01=Isochronous, 10=Bulk, 11=Interrupt).
- Command-issuance caveats repeated for every DEPCMDn command (`txt:27335-27345` etc.): if
  operating at USB2.0 speeds and `GUSB2PHYCFG[6]` or `[8]` is set, it must be cleared before
  issuing the command and may be re-set after completion; command timeout should be > 1ms;
  software must keep servicing event interrupts while polling `CmdAct` to avoid deadlock, or use
  `CmdIOC` (bit 8) to get a completion interrupt instead of polling.

## 8. DEPSTARTCFG command detail (Section 3.2.2.8/"Command 9", `p.549-550`, `txt:27818-27835`)

> "Software issues this command under the following conditions:
> - After power-on-reset with XferRscIdx=0 before starting to configure Endpoints 0 and 1.
>   CmdIOC must be set to '0' and software must poll the CmdAct bit to determine when the
>   command is complete because Endpoint 0 is not yet configured with a valid interrupt number.
> - With XferRscIdx=2 when it receives SetConfiguration before starting to configure Endpoints >
>   1. CmdIOC may be set to '0' or '1'.
> This command should always be issued to Endpoint 0 (DEPCMD0). Hardware resets the transfer
> resource allocation to the value in the XferRscIdx parameter (must be 0 or 2) upon receiving
> this command."

This confirms the power-on value must be `XferRscIdx=0` and it must precede EP0/EP1 DEPCFG —
matching Table 4-1 step 6 exactly.

## 9. DEPXFERCFG command detail (Section 3.2.2.2, `p.544`, `txt:27507-27545`, Table 3-4)

> "There must be only one transfer resource allocated per endpoint. Start Transfer causes the
> use of the transfer resource. End Transfer or an XferComplete event releases the transfer
> resource. If software attempts to allocate more transfer resources than have been configured
> in the hardware, this command will return an error."

Parameter 0 bits[15:0] `NumXferRes` "must be set to 1."

## 10. Register-level bit-position facts backing the sequence (all cross-checked against the
    flow-chapter text above)

- **DCTL** register (`p.329-331`, `txt:17800-17958`, Table 1-101), offset `0xc704`, layout:
  - **bit 31 RUN_STOP** (R/W): "The software writes 1 to this bit to start the device controller
    operation... After power-on reset and CSR initialization, the software must write 1 to this
    bit to start the device controller. The controller does not signal connect to the host until
    this bit is set." Value after reset 0x0.
  - **bit 30 CSFTRST** (R/W1S — write-1-to-set, self-clearing): "Resets all the clock domains...
    clears the interrupts and all the CSRs except GSTS, USB31_IP_NAME, GGPIO, GUID,
    GUSB2PHYCFGn, GUSB3PIPECTLn, DCFG, DCTL, DEVTEN, and DSTS registers... All module state
    machines (except the SoC Bus Completer Unit) are reset to IDLE, and all TxFIFOs/RxFIFO are
    flushed... This is a self-clearing bit; the core clears this bit after all necessary logic is
    reset in the core and all the PHY clocks are active/running after PHY reset, **which may take
    several milliseconds** depending on the PHY's clock latency. Software can have a poll rate of
    1 ms or more to check if this bit has been cleared." Value after reset 0x0, Testable:
    writeAsRead, Volatile: true.
  - Note the important corollary: **DEVTEN and DCFG are explicitly exempt from being cleared by
    CSftRst** — so if a BFM/checker assumes DEVTEN/DCFG revert to reset values after CSftRst,
    that assumption is wrong per this register description; a real init sequence issuing
    CSftRst then relying on stale DEVTEN/DCFG contents would need this called out.
  - Confirmed independently in the Debug-Capability chapter (`p.` n/a shown, `txt:31283-31287`):
    "When the software sets HCRST (in host mode) or DCTL[30] (CSftRst) (in device mode), it
    invokes a 'Chip Hardware Reset.' This causes all asynchronous resets in the controller to be
    asserted... the PHYs are reset."

- **DCFG** register (`p.325-328`, `txt:17595-17793`, Table 1-100), offset `0xc700`:
  - bits[2:0] `DEVSPD`: `0x5`=Enhanced SuperSpeed, `0x4`=SuperSpeed, `0x0`=High-Speed,
    `0x1`=Full-Speed. "the actual bus speed is determined only after the chirp sequence is
    completed."
  - bits[9:3] `DEVADDR`: "Program this field after every SetAddress request. Reset this field to
    zero after USB reset."
  - bits[16:12] `INTRNUM`: interrupt/EventQ number for non-endpoint-specific DEVT events (this is
    the field referenced by the Event-Buffer §3 "DEVT events written to the Event Buffer
    specified in DCFG.IntrNum" statement).
  - Register description itself: "This register configures the controller in Device mode after
    power-on or after certain control commands or enumeration. **Do not make changes to this
    register after initial programming**" (except the documented per-event DevAddr/DevSpd
    updates above — i.e., that caution is about ad hoc changes, not the documented flow steps).

- **DEVTEN** register (`p.340-342`, `txt:18464-18615`, Table 1-102), offset `0xc708`:
  bit0=`DISSCONNEVTEN`, **bit1=`USBRSTEVTEN`**, **bit2=`CONNECTDONEEVTEN`**,
  **bit3=`ULSTCNGEN`**, bit4=`WKUPEVTEN`, bit5=`HibernationReqEvtEn`, bit6=`U3L2L1SuspEn`,
  bit7=`SOFTEVTEN`, bit8=`L1SUSPEN`, bit9=`ERRTICERREVTEN`, bit12=`VENDEVTSTRCVDEN`,
  bit14=`L1WKUPEVTEN`, bit15=`LDMEVTEN`. All reset to 0. So Table 4-1's "at a minimum, enable USB
  Reset, Connection Done, and USB/Link State Change events" is concretely **`DEVTEN = 0x0E`**
  (bits 3,2,1 set) as the minimum bring-up value — a directly checkable numeric fact.

- **DALEPENA** register (`p.356`, `txt:19246-19286`, Table 1-107), offset `0xc720`, bits[31:0]
  `USBACTEP`: "Bit[0]: USB EP0-OUT Bit[1]: USB EP0-IN... The entity programming this register
  must set bits 0 and 1 because they enable control endpoints that map to physical endpoints
  (resources) **after USBReset**." Matches Table 4-1's "writing 0x3 to this register" for EP0
  OUT+IN. Hardware auto-clears bits other than EP0-OUT/IN on USB Reset detection.

- **GCTL.PRTCAPDIR** (bits 13:12, `p.118-119`, `txt:6776-6816`, part of Table 1-23): `2'b10` =
  Device configuration (must be set for device mode; this precedes the device-mode bring-up
  entirely and is called out in the mode-switch flow: "Switching from Host to Device: 1. Set
  GCTL[13:12] (PrtCapDir) to 2'b10 (Device mode). 2. Follow the steps in the 'Device Power-On or
  Soft Reset' section..." — confirming PRTCAPDIR=2'b10 is a documented precondition/first
  half-step logically before Table 4-1's own sequence in a DRD part, though for a
  device-mode-only-configured core this is fixed at reset and not a runtime step).

- **GUCTL.REFCLKPER** (bits 31:22, `p.142`, `txt:8031-8074`, Table 1-30): "This field indicates
  the period of ref_clk, in terms of nanoseconds... This field needs to be updated during
  power-on initialization." **Caveat/cross-reference**: the GUCTL register's own top-level
  description states "This register provides a few options for the software to control the
  controller behavior **in Host mode**" (`txt:18033-18034` region /`txt:8033-8034`) — i.e.
  REFCLKPER as documented here is presented under Host-mode register semantics, and it does NOT
  appear as a row in Device-mode Table 4-1 (the device-mode bring-up table has no GUCTL/REFCLKPER
  row at all). This is a genuine cross-reference nuance: reference-clock period programming is
  real and does say "needed during power-on initialization" generically, but the concrete
  device-mode bring-up table (Table 4-1) does not list GUCTL among the registers to touch — so a
  checker should not require a device-mode BFM pattern to write GUCTL/REFCLKPER as part of the
  documented device bring-up sequence; that expectation would be over-reaching based on this
  source. (No separate device-mode "reference clock setup" register step exists in Ch.4; clock
  domain selection in device mode is limited to `GCTL.RAMCLKSEL` per §5 above, and PHY interface
  timing fields folded into `GUSB2PHYCFG` per Table 4-1's own row.)

- **Event-buffer registers** GEVNTADRLO/HI/GEVNTSIZ/GEVNTCOUNT: see §3 above for full detail;
  offsets `0xc400/0xc404/0xc408/0xc40c + i*0x10` for interrupter `i`.

## 11. Net checklist a verification engineer can apply directly (derived, not paraphrase-vague)

For a **power-on/soft-reset device-mode bring-up BFM pattern**, the documented, checkable order
constraints are://
1. DCTL.CSftRst=1 must be written, and the pattern should wait for it to read back 0, **before**
   any other device-register programming. (`txt:28265-28273`, Table 4-1 first row + ordering
   sentence.)
2. GEVNTADRn and GEVNTSIZn must be written before GEVNTCOUNTn is written (to 0). (`txt:28631-28640`.)
3. DEPSTARTCFG (XferRscIdx=0) must be issued (to DEPCMD0) before any DEPCFG for EP0/EP1.
   (`txt:28325-28328`, `txt:27826-27829`.)
4. DEPCFG must be issued for EP0 **before** EP1 (explicit ordering note, twice — once for DEPCFG,
   once for DEPXFERCFG). (`txt:28329-28337`, `txt:28339-28341`.)
5. DEPXFERCFG for EP0 then EP1 must follow DEPCFG for EP0/EP1. (`txt:28339-28341`.)
6. A setup-TRB DEPSTRTXFER on DEPCMD0 should occur before DALEPENA is written (Table 4-1 orders
   it that way, step 9 before step 10). (`txt:28350-28357`.)
7. **DALEPENA=0x3 must be written only after DEPSTARTCFG + DEPCFG(EP0) + DEPCFG(EP1) +
   DEPXFERCFG(EP0) + DEPXFERCFG(EP1)** — i.e., never before any endpoint configuration exists.
   (`txt:28329-28357`; corroborated by DALEPENA's own "after USBReset" / physical-resource-mapped
   language at `txt:19270-19275`.)
8. DCTL.RunStop=1 must be the last step of the whole power-on sequence, strictly after DALEPENA.
   (`txt:28266`, `txt:28357-28361`.)
9. This DALEPENA-after-DEPCFG rule is specific to the **power-on bring-up** table (4.1.1); it does
   NOT generalize to the SetConfiguration flow (4.1.5), where DALEPENA is legitimately written
   *before* new DEPCFG commands too (to disable=0x3 old endpoints) and then again *after* (to
   enable new ones) — a checker must distinguish which lifecycle phase a given DALEPENA write
   belongs to before flagging it. (`txt:28448-28478`.)

---

# Extraction complete.
Persisted as Project Memory records (see harness output) under category `programming_guide`.
