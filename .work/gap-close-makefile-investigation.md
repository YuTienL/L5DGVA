# Investigation: 5 files missing from `dv_harness/uvm_generator/templates/sim_scripts/`

Scope: `analyze_sim.sh`, `apb_timing_report.sh`, `dpdm_report.sh`, `irq_report.sh`,
`check/gen_scaledown.py` — present in `USB_UVM_Handoff/sim/scripts/` (and `check/`),
absent from the migrated template tree. This closes the gap CLAUDE.md's
"Architecture-conformance audit" section already flags as open (2026-09-02
consolidation-status note).

Governing constraints applied throughout: (1) No Golden-Reference Content Mining
(CLAUDE.md "No Golden-Reference Content Mining") — USB_UVM_Handoff content may be
read for structural/organizational conformance and cited as a **worked example**,
never mined as the source of a different project's protocol content; (2) the
Harness is generic across USB/PCIe/MIPI/Ethernet/CAN-FD/AMBA4 etc, so any migrated
template must abstract to protocol-neutral vocabulary (`TARGET_IP`/`IP_PREFIX`,
placeholder signal-path variables) with USB's real values kept only as an
explicitly-labeled illustration, not as the generic vocabulary itself.

## The established genericization convention (read from the already-migrated files)

Read in full: `templates/sim_scripts/Makefile` (3650 lines), `lsf_regress.sh`,
`waves.tcl`, `ip_run.sh`, and one migrated `check/*.py` (`reg_audit.py`) for
comparison. The convention is consistent across all of them:

1. **Two protocol-vocabulary variables carried everywhere**: `TARGET_IP` (upper-case,
   e.g. `USB`) and `IP_PREFIX` (lower-case with trailing underscore, e.g. `usb_`),
   both `?=`-overridable (Makefile) or `${VAR:-default}` (shell) or
   `os.environ.get('TARGET_IP','USB')` (Python), defaulting to USB so the template
   "still runs standalone unmodified" as the original proving-ground project.
   `IP_PREFIX_STEM` is the same value with the trailing `_` stripped, for bare-name
   cases.
2. **A `GENERIC TEMPLATE NOTE` (or `GENERIC TEMPLATE:` docstring) block at the top
   of every migrated file** stating explicitly which part is protocol-agnostic
   STRUCTURE (grouping/logic/flow) versus which part is a real, hardcoded USB
   worked example that must be **re-derived from the current DUT's own RTL/VIP**
   before reuse on another protocol — never assumed to carry over.
3. **Hierarchical/instance paths and register/signal names are NOT parameterized
   away** into generic variables when they are real RTL facts (e.g. `sysn063`,
   `u_lan063`, `ss_cpu_m_*`, `DWC_usb31`, `usb0_dp`/`usb0_dm`). Instead they are
   centralized into a handful of named path variables near the top of the file
   (waves.tcl's `TB`/`DUT`/`SSVOUT`/`BIND`/`APBARB`/`LAUNCH`/`IP0`/`IP1`) so "you
   change TB and DUT here rather than editing every line below" — genericity comes
   from **one edit point**, not from a plusarg/knob, because a hierarchical path is
   a DUT fact, not a runtime choice.
4. **Protocol-specific enum/knob values (SPEED, PHY_SIM, etc.) are kept as real
   USB values with a comment explaining they are this-template's-original-project's
   values and must be replaced with `TARGET_IP`'s own axis**, or the whole knob
   dropped if the new protocol has no equivalent axis.
5. Every migrated file's header explains **why** it exists and what question it
   answers (waves.tcl's "the first useful question is almost never one signal, it's
   one of five groups"), preserving the reasoning, not just the mechanism.

This is the exact pattern to reproduce for the 5 gap files.

---

## 1. `analyze_sim.sh`

**Real content (in full):**
```sh
#!/bin/sh
# Quick summary of one run's sim.log: latest timestamp, LSF job status (if
# still running), error/warning counts, and a breakdown of error signatures.
# Usage: sh analyze_sim.sh <path-to-sim.log> [lsf-job-id]
LOG=${1:?usage: sh analyze_sim.sh <path-to-sim.log> [lsf-job-id]}
JOBID=${2:-}

echo LATEST_TIME:
tail -c 300 "$LOG" | grep -aoE "[0-9]+\.[0-9]+ ns" | tail -1
echo JOBSTAT:
if [ -n "$JOBID" ]; then
  bjobs -a "$JOBID" 2>&1 | tail -1
else
  echo "(no job id given -- pass one as the 2nd argument to check LSF status)"
fi
echo ERRCOUNT:
grep -ac UVM_ERROR "$LOG"
echo DMASB_COUNT:
grep -ac usb_dma_sb "$LOG"
echo FINALCHECK:
grep -acE "SvtTestEpilog:|FINAL_CHECK\(" "$LOG"
echo ---ERRSIGNATURES---
grep -a UVM_ERROR "$LOG" | sed -E "s/^UVM_ERROR //" | grep -oE "\[[a-zA-Z_0-9]+:[a-zA-Z_0-9]+\]|\[register_fail:[^]]+\]" | sort | uniq -c | sort -rn
```

**(1) Genuinely protocol-specific, or structurally generic?**
Structurally generic. 21 of 24 lines are pure log-triage mechanics that apply to
*any* protocol's `sim.log`: tail for the latest simulated-time stamp, `bjobs` job
status, `UVM_ERROR` count (a UVM concept, not a USB one), a `FINAL_CHECK`/
`SvtTestEpilog` marker count (both are UVM/SVT VIP conventions used across every
protocol VIP in this family, not USB-only), and an error-signature histogram keyed
on the `[category:subcategory]` bracket convention the harness's own scoreboards
already use generically. Exactly **one line** is protocol content:
```sh
echo DMASB_COUNT:
grep -ac usb_dma_sb "$LOG"
```
`usb_dma_sb` is the literal name of this project's USB DMA scoreboard component. It
is a single grep target, not a structural dependency — trivially swapped for any
other protocol's scoreboard name.

**(2) Referenced by the Makefile or migrated scripts?**
No. Grepped the full migrated `Makefile`, `lsf_regress.sh`, `ip_run.sh`, `waves.tcl`
and every migrated `check/*.py` — zero references to `analyze_sim.sh`. Also
confirmed the **original** `USB_UVM_Handoff/sim/scripts/Makefile` (3529 lines) does
not reference it either. It is a standalone, hand-invoked debug utility ("Usage: sh
analyze_sim.sh <path-to-sim.log> [lsf-job-id]"), not wired into any build/regress
target in either tree.

**(3) Migration requirement.**
Trivial. Add the standard `GENERIC TEMPLATE NOTE` header (this script's logic is
protocol-agnostic log triage), and parameterize the one USB-specific grep target
the same way `Makefile`/`ip_run.sh` parameterize job-name prefixes — via
`IP_PREFIX`:
```sh
IP_PREFIX="${IP_PREFIX:-usb_}"
...
echo DMASB_COUNT:
grep -ac "${IP_PREFIX}dma_sb" "$LOG"
```
with a comment that `usb_dma_sb` was this template's original project's real
scoreboard-component name and the current project's scoreboard name must be
confirmed against its own environment (`env/*_scoreboard.sv`) rather than assumed
to match `${IP_PREFIX}dma_sb` literally, exactly the caveat style already used for
`VERB_COMP` shorthands in the Makefile. No other change needed.

---

## 2. `apb_timing_report.sh`

**Real content (in full):**
```sh
#!/bin/sh
# Reports port1 APB psel/pready/penable over a time window. Usage:
#   sh apb_timing_report.sh <fsdb-file> [begin-time-ns] [end-time-ns]
V=$VERDI_HOME/bin/fsdbreport
F=${1:?usage: sh apb_timing_report.sh <fsdb-file> [begin-time-ns] [end-time-ns]}
BT=${2:-0}
ET=${3:-1000000}

$V $F -bt $BT -et $ET -verilog -s "/sysn063/u_lan063/u_ss_vout/u_usbtop[1]/usb_s_psel" -o /tmp/p1_psel.txt > /tmp/p1_psel.log 2>&1
$V $F -bt $BT -et $ET -verilog -s "/sysn063/u_lan063/u_ss_vout/u_usbtop[1]/usb_s_pready" -o /tmp/p1_pready.txt > /tmp/p1_pready.log 2>&1
$V $F -bt $BT -et $ET -verilog -s "/sysn063/u_lan063/u_ss_vout/u_usbtop[1]/usb_s_penable" -o /tmp/p1_penable.txt > /tmp/p1_penable.log 2>&1

echo DONE
wc -l /tmp/p1_psel.txt /tmp/p1_pready.txt /tmp/p1_penable.txt
```

**(1) Genuinely protocol-specific, or structurally generic?**
Both, cleanly separable — same split as `waves.tcl` already made explicit. The
**shape** is generic and directly recognizable as `waves.tcl`'s "3b APB slave
decode" group re-expressed as a batch/headless `fsdbreport` export instead of an
interactive Verdi `wvCreateGroup`/`wvAddSignal` call: take an FSDB path plus an
optional `[begin,end]` time window, run `$VERDI_HOME/bin/fsdbreport` once per
signal of interest, write each to its own text file, report line counts. That
control flow (positional args with defaults, one `fsdbreport` invocation per
signal, single `DONE` + `wc -l` summary) applies to reporting *any* signal group of
*any* protocol's testbench — APB, or a target protocol's own register bus, or link
state, exactly like `waves.tcl` groups 1–8 do for the interactive case.
What is **not** generic is every hardcoded hierarchical path
(`/sysn063/u_lan063/u_ss_vout/u_usbtop[1]/usb_s_*`) and the port-1-only,
psel/pready/penable-only scope baked directly into three separate command lines —
these are real RTL facts about this template's original USB SoC (`sysn063` /
`u_lan063` / `u_ss_vout` / `u_usbtop[1]`), identical in kind to `waves.tcl`'s own
`TB`/`DUT`/`SSVOUT` signal paths, which that file already treats as "a real worked
EXAMPLE from that USB project's own DUT and must be re-derived from the CURRENT
DUT's own RTL."

**(2) Referenced by the Makefile or migrated scripts?**
No. No reference anywhere in the migrated tree, and no reference in the original
`USB_UVM_Handoff/sim/scripts/Makefile` either — confirmed by the same grep as
above. It is a standalone, hand-invoked Verdi/FSDB debug utility, siblings to
`apb_timing_report.sh`/`dpdm_report.sh`/`irq_report.sh` all following the identical
`fsdbreport`-wrapper shape, none referenced by any build target.

**(3) Migration requirement.**
Needs the `waves.tcl` treatment, not a trivial parameterization:
- Add the standard `GENERIC TEMPLATE NOTE` header identifying the reusable shape
  (headless FSDB signal-group export via `fsdbreport`) versus the worked-example
  content (the actual paths).
- Centralize the hierarchical prefix into named path variables exactly as
  `waves.tcl` does, reusing the *same* variable names so the two files agree:
  `TB="sysn063"`, `DUT="$TB.u_lan063"`, `SSVOUT="$DUT.u_ss_vout"`,
  `IPTOP_IDX1="[1]"`, plus `TARGET_IP`/`IP_PREFIX` so the instance name
  `u_${IP_PREFIX}top$IPTOP_IDX1` follows the Makefile/waves.tcl vocabulary instead
  of a literal `u_usbtop[1]`.
- Turn the fixed three-line unrolled body into a small loop over a signal list
  (mirroring `waves.tcl`'s `addGroup` helper design, adapted to `fsdbreport`'s CLI
  rather than Verdi's Tcl API), so a different protocol's register-bus signal
  names are a data change, not a structural edit — e.g.:
  ```sh
  SIGNALS="${SIGNALS:-${SSVOUT}.u_${IP_PREFIX}top${IPTOP_IDX}.usb_s_psel:psel
           ${SSVOUT}.u_${IP_PREFIX}top${IPTOP_IDX}.usb_s_pready:pready
           ${SSVOUT}.u_${IP_PREFIX}top${IPTOP_IDX}.usb_s_penable:penable}"
  ```
  with a comment that the leaf names (`usb_s_psel` etc.) are this template's
  original USB project's own register-bus slave-select signal names and must be
  re-derived from the current DUT's RTL exactly as `waves.tcl` group 3b already
  says for the interactive case — do not assume they carry over.
- Note in the header that this script and `waves.tcl` group "3b APB slave decode"
  answer the same question in two different tools (headless script vs. interactive
  GUI) and should be kept in sync if one is updated — worth flagging explicitly
  since nothing currently states that relationship even in the source project.

---

## 3. `dpdm_report.sh`

**Real content (in full):**
```sh
#!/bin/sh
# Reports both ports' USB 2.0 dp/dm lines over a time window. Usage:
#   sh dpdm_report.sh <fsdb-file> [begin-time-ns] [end-time-ns]
V=$VERDI_HOME/bin/fsdbreport
F=${1:?usage: sh dpdm_report.sh <fsdb-file> [begin-time-ns] [end-time-ns]}
BT=${2:-0}
ET=${3:-1000000}

$V $F -bt $BT -et $ET -verilog -s "/sysn063/u_lan063/u_ss_vout/u_usbtop[0]/u_udc_usb31_top/dp" -o /tmp/p0_dp.txt > /tmp/p0_dp.log 2>&1
$V $F -bt $BT -et $ET -verilog -s "/sysn063/u_lan063/u_ss_vout/u_usbtop[0]/u_udc_usb31_top/dm" -o /tmp/p0_dm.txt > /tmp/p0_dm.log 2>&1
$V $F -bt $BT -et $ET -verilog -s "/sysn063/u_lan063/u_ss_vout/u_usbtop[1]/u_udc_usb31_top/dp" -o /tmp/p1_dp.txt > /tmp/p1_dp.log 2>&1
$V $F -bt $BT -et $ET -verilog -s "/sysn063/u_lan063/u_ss_vout/u_usbtop[1]/u_udc_usb31_top/dm" -o /tmp/p1_dm.txt > /tmp/p1_dm.log 2>&1

echo DONE
wc -l /tmp/p0_dp.txt /tmp/p0_dm.txt /tmp/p1_dp.txt /tmp/p1_dm.txt
```

**(1) Genuinely protocol-specific, or structurally generic?**
Same split as `apb_timing_report.sh`, one level more USB-specific in its *subject
matter*: `dp`/`dm` (USB 2.0 differential data-plus/data-minus lines) are a
USB-protocol electrical concept with no direct equivalent in, say, AMBA AXI or
MIPI CSI-2 (which have their own physical-layer pairs — PCIe has TX/RX
differential pairs, MIPI has clock/data lanes, etc.). This is the one file of the
five that is closest to being "genuinely protocol content" in its **subject**
(which two wires to look at), matching the same `waves.tcl` group 5 "USB pads"
territory — but its **script shape** (fsdbreport-per-signal, time-windowed, N
outputs + a `wc -l` summary) is identical to `apb_timing_report.sh` and
`irq_report.sh` and is 100% reusable. Confirmed against `waves.tcl`'s own header,
which states groups 5/5b answer a protocol-general question ("is there anything at
all on the wire") using USB's own pad names as the worked instance.

**(2) Referenced?** No — same grep result as above, no reference anywhere in either
tree.

**(3) Migration requirement.**
Same `waves.tcl`-style treatment as `apb_timing_report.sh`: centralize
`TB`/`SSVOUT`/`IPTOP_IDX0`/`IPTOP_IDX1` (reuse `waves.tcl`'s exact variable names),
loop over a `SIGNALS` list instead of four unrolled command lines, and rename the
file/variables to a protocol-neutral term for "this generation's physical-layer
signal pair(s) of interest" in the header — while being explicit that `dp`/`dm` are
this template's original USB 2.0-specific electrical pair names and the
current `TARGET_IP`'s own physical-layer signal names (differential pair, lane,
whatever the protocol calls it) must be substituted; a protocol whose physical
layer has no such concept (e.g. a pure register-bus target with no serial PHY) can
drop this script's template entirely rather than force-fit it. This is the file
where the "GENERIC TEMPLATE NOTE" header must be most explicit that the reusable
part is narrower than in the other three — it is the fsdbreport-export **shape**
only, not the electrical concept.

---

## 4. `irq_report.sh`

**Real content (in full):**
```sh
#!/bin/sh
# Reports both ports' usbirq/interrupt[19:0] over a time window. Usage:
#   sh irq_report.sh <fsdb-file> [begin-time-ns] [end-time-ns]
V=$VERDI_HOME/bin/fsdbreport
F=${1:?usage: sh irq_report.sh <fsdb-file> [begin-time-ns] [end-time-ns]}
BT=${2:-0}
ET=${3:-2000000}

$V $F -bt $BT -et $ET -verilog -s "/sysn063/u_lan063/u_ss_vout/u_usbtop[0]/u_usbwrapper_usb/usbirq" -o /tmp/p0_irq.txt > /tmp/p0_irq.log 2>&1
$V $F -bt $BT -et $ET -verilog -s "/sysn063/u_lan063/u_ss_vout/u_usbtop[1]/u_usbwrapper_usb/usbirq" -o /tmp/p1_irq.txt > /tmp/p1_irq.log 2>&1
$V $F -bt $BT -et $ET -verilog -s "/sysn063/u_lan063/u_ss_vout/u_usbtop[0]/u_udc_usb31_top/interrupt[19:0]" -o /tmp/p0_intr.txt > /tmp/p0_intr.log 2>&1
$V $F -bt $BT -et $ET -verilog -s "/sysn063/u_lan063/u_ss_vout/u_usbtop[1]/u_udc_usb31_top/interrupt[19:0]" -o /tmp/p1_intr.txt > /tmp/p1_intr.log 2>&1

echo DONE
wc -l /tmp/p0_irq.txt /tmp/p1_irq.txt /tmp/p0_intr.txt /tmp/p1_intr.txt
```

**(1) Genuinely protocol-specific, or structurally generic?**
Structurally generic (interrupt lines are a cross-protocol concept — every
protocol in this Harness's scope has some interrupt/event-status signal, and
`waves.tcl` group 8 "Interrupts and error status" already treats this generically:
"Nothing in the environment currently checks these... so watching them here is the
only way they are seen at all"). Same shape as the previous two: fsdbreport-per-
signal, time-windowed, N outputs + `wc -l`. The only default-value difference from
the other two scripts is `ET=${3:-2000000}` (2,000,000 ns vs 1,000,000 ns) — a
tuning constant, not a structural one, presumably because interrupt-worthy events
happen later in this USB project's own patterns than APB register writes do.

**(2) Referenced?** No — same result.

**(3) Migration requirement.**
Same `waves.tcl`-style treatment: centralize `TB`/`SSVOUT`/`IPTOP_IDX0/1` (again
reusing `waves.tcl`'s variable names for consistency across the three fsdbreport
scripts), loop over a `SIGNALS` list built from `${IP_PREFIX}wrapper_${IP_PREFIX_STEM}.usbirq`-shaped
placeholders instead of the four hardcoded `u_usbwrapper_usb`/`interrupt[19:0]`
paths, and keep the `ET` default's rationale (interrupts show up later than
register writes) as an explicit comment rather than a bare number, matching the
level of justification the Makefile gives every one of its own defaults
(`TOTAL_RUNTIME`, `VIP_RXDET_DELAY_US`, etc.).

---

## Consolidated note on the three `*_report.sh` scripts

All three (`apb_timing_report.sh`, `dpdm_report.sh`, `irq_report.sh`) are the same
one script differing only in (a) which signal paths and (b) the default end-time.
Rather than migrate them as three independent templates that will drift the way
`RENAME`/legacy-dup logic already shows single-source-of-truth problems can appear
elsewhere in this codebase, the stronger migration is a **single parameterized
template** — e.g. `fsdb_signal_report.sh` — taking a `SIGNALS` (name:path pairs) and
`ET` default as inputs, with three **worked-example invocations** documented in its
header (the APB/dp-dm/interrupt cases, each citing the real USB paths as the
worked example per the established convention). This avoids tripling the
`GENERIC TEMPLATE NOTE` boilerplate and — more importantly — avoids the exact
copy-paste-drift failure mode the Makefile's own comments already call out
elsewhere in this codebase (the `SUITE=`/pattern-directory hardcoded-list defect
"a third place it had been copied into"). If the team prefers keeping three
separate files for discoverability (matching the source project's own file-per-
question layout, and matching how `waves.tcl` also keeps its 8 groups in one file
rather than 8 files — so precedent actually points either way), each should still
`source` or otherwise reuse one shared loop/arg-parsing implementation rather than
tripling the `fsdbreport` invocation boilerplate three times independently.

---

## 5. `check/gen_scaledown.py`

**Real content (in full, 106 lines) — key excerpts:**
```python
"""Generate the scale-down timer assignments for usb_top_cfg.sv.

Every field name is checked against svt_usb_configuration.sv before it is
emitted. The xls names and the VIP names are NOT the same -- the sheet says
'tuch' where the class declares 'tuch_hs' -- so a hand transcription of 22
fields x up to 6 family members would have been wrong somewhere.
"""
import os, re, xlrd

VIP_HOME = os.environ.get('VIP_HOME', '')
SRC = os.path.join(VIP_HOME, 'src/sverilog/vcs/svt_usb_configuration.sv') if VIP_HOME \
      else r'/path/to/your/VIP_HOME/src/sverilog/vcs/svt_usb_configuration.sv'
XLS = os.environ.get('SCALEDOWN_XLS', r'/path/to/rtl_vip_scaledown_mapping.xls')
...
def family(base):
    out = [base]
    for suf in ('_min', '_max', '_longint', '_min_longint', '_max_longint'):
        if base + suf in declared:
            out.append(base + suf)
    return [n for n in out if n in declared]

RENAME = {'tuch': 'tuch_hs'}
...
for label, col in (('USB 2.0', 1), ('SuperSpeed', 0)):
    ...
    # legacy lfps_tXX_tYY_uZ_* naming: this VIP version calls these
    # uN_exit_lfps_respond_after_time / _transmit_for_time, and the
    # sheet lists BOTH spellings, so the modern one is already covered.
    mod = re.match(r'lfps_t11_t10_(u[123])_min', vname)
    ...
    open('gen_%s.svh' % label.replace(' ', '').replace('.', ''), 'w', ...)
```

**(1) Genuinely protocol-specific, or structurally generic?**
Mixed, more deeply than the shell scripts — this is the hardest of the five to
genericize cleanly. The **framework** is protocol-agnostic and directly parallels
the already-migrated `check/reg_audit.py`'s own "GENERIC TEMPLATE" split: read a
VIP configuration class's declared field names via regex, read an external
vendor scale-down mapping spreadsheet, cross-check every mapped field actually
exists in the VIP class (catching hand-transcription errors), classify each row
as resolved/legacy-duplicate/unparsed/unmatched, and emit SystemVerilog assignment
lines into a generated `.svh`. That shape — "VIP class is ground truth for field
names, external vendor doc is ground truth for values, cross-check and emit,
never hand-transcribe" — applies to any VIP-based protocol whose vendor ships a
scale-down/timing mapping doc separate from the VIP source.
What does **not** generalize without protocol-specific knowledge, and is baked in
as literal data rather than structure:
- `SRC` points at `svt_usb_configuration.sv` by name — a different protocol's VIP
  ships a differently-named configuration class (verify the real name per VIP,
  exactly as `reg_audit.py`'s header already warns for register-macro names:
  "verify this actual class/file name against TARGET_IP's real VIP").
- `RENAME = {'tuch': 'tuch_hs'}` is a one-off USB-VIP-specific spreadsheet-vs-class
  name mismatch discovered by hand; a different VIP's spreadsheet will have its own
  (possibly empty, possibly different) mismatch set — this cannot be generalized,
  only re-derived per VIP/spreadsheet pair.
- The `('USB 2.0', 1), ('SuperSpeed', 0)` column/label pairs assume the vendor
  spreadsheet has exactly two named mode columns matching USB's own speed-mode
  axis (mirrors the Makefile's own `SPEED` USB-specific enum, which the Makefile
  already documents as "adapt to TARGET_IP's own speed/mode axis... a protocol
  with no such axis can drop this knob entirely"). A protocol VIP's own scale-down
  doc may have a different number of mode columns, or none.
- The `lfps_t11_t10_(u[123])_min` / `lfps_t13_t11_(u[123])_min` legacy-dedup regexes
  are literal USB SuperSpeed LFPS (Low-Frequency Periodic Signaling) timer-naming
  history — meaningless outside USB.
- The `_min/_max/_longint/_min_longint/_max_longint` family-suffix set is this
  VIP's own field-naming convention for value-range variants; a different VIP may
  use a different suffix vocabulary or none.
- Output filename `gen_%s.svh` and the destination class member path
  `host_cfg[p].<field>` are specific to this template's `usb_top_cfg.sv`/
  `usb_scaledown_timers.svh` consumer, itself unmigrated (this script's *consumer*
  is USB-specific protocol content proper, out of scope for a generic template by
  the "No Golden-Reference Content Mining" rule — protocol timer-value content
  belongs to primary VIP/DUT sourcing per project, never mined from USB's).

**(2) Referenced by the Makefile or migrated scripts?**
No direct invocation from the Makefile or any migrated `check/*.py` — it is a
manually-run, one-time/occasional regeneration tool ("run it when the spreadsheet
changes"), not a per-build or per-check target. It **is** referenced, however, as
provenance inside its own *output's consumer*:
`USB_UVM_Handoff/uvm/tb/env/usb_scaledown_timers.svh` carries
`// GENERATED. Do not hand edit. // generator : sim/scripts/check/gen_scaledown.py`
and two inline comments warning that specific hand-patched values will be
silently reverted by "a future gen_scaledown.py re-run" unless the spreadsheet is
updated too. So its role in the source project is design-time codegen provenance
for a hand-auditable `.svh`, not a regression-time check like the other
`check/*.py` scripts that migrated (`reg_audit.py`, `vip_guards.py`, etc., which
run as part of `make check`).

**(3) Migration requirement.**
This is a template-the-framework, not template-the-content migration, matching
`reg_audit.py`'s precedent exactly:
- Add the same `GENERIC TEMPLATE:` docstring split used in `reg_audit.py`: framework
  (regex-extract declared fields from a VIP config class; cross-check spreadsheet
  rows against them; classify legacy/unparsed/unmatched; emit assignments) is
  reusable, content (class filename, `RENAME` map, mode-column labels, legacy-dedup
  regexes, suffix family set, output naming) is this template's original USB
  worked example and must be re-derived per project from that project's own VIP
  class source and vendor scale-down doc — never assumed to carry over.
- Parameterize what the Makefile/other scripts already parameterize:
  `TARGET_IP`/`IP_PREFIX` env vars, with `SRC`'s class filename built from
  `IP_PREFIX_STEM` where the VIP naming convention actually matches
  (`svt_{IP_PREFIX_STEM}_configuration.sv`), same caveat as `reg_audit.py`'s "not
  guaranteed to equal IP_PREFIX_STEM for every VIP."
- Make `RENAME`, the mode/column list, the legacy-dedup regex list, and the family
  suffix set all **top-of-file data** (already true for `RENAME` and the suffix
  tuple; the mode/column list and dedup regexes need lifting out of the loop body
  the same way) with a comment block marking them "USB's real instance of this
  mapping — confirm equivalents against the current VIP/spreadsheet before
  reusing," per the CLAUDE.md instruction to keep concrete illustrations but never
  emit them as generic vocabulary.
- Output path/consumer naming (`gen_%s.svh`, `host_cfg[p].<field>`) should become a
  configurable prefix/pattern rather than hardcoded, since a future project's
  scale-down config class will not be named `usb_top_cfg.sv`.

---

## Summary table

| File | Structurally generic? | Called by Makefile/migrated scripts? | Migration effort |
|---|---|---|---|
| `analyze_sim.sh` | Yes, 21/24 lines; 1 line (`usb_dma_sb` grep target) is protocol content | No — standalone debug utility, not referenced anywhere in either tree | Trivial: header + `IP_PREFIX`-parameterize one grep target |
| `apb_timing_report.sh` | Yes, shape only (fsdbreport export loop); paths are RTL facts | No | Moderate: `waves.tcl`-style path-variable centralization + signal-list loop (same treatment as `dpdm_report.sh`/`irq_report.sh` — consider one shared template) |
| `dpdm_report.sh` | Shape yes; subject (`dp`/`dm`) is USB-2.0-specific and may not apply to every protocol | No | Moderate, same as above, but header must be explicit that a protocol with no equivalent physical pair drops this template |
| `irq_report.sh` | Yes, shape only; interrupts are a cross-protocol concept | No | Moderate, same treatment |
| `check/gen_scaledown.py` | Framework yes (VIP-class-vs-vendor-doc cross-check codegen); RENAME/columns/dedup-regexes/suffixes are USB-VIP-specific data | No direct call; is cited as generator provenance inside its own output file's header comments (USB-side only) | Higher: same `reg_audit.py`-style GENERIC TEMPLATE split, lift more literals to top-of-file data, `TARGET_IP`/`IP_PREFIX` parameterize class filename |

None of the 5 files are wired into `make` targets or called by any already-migrated
script in either the source or the migrated tree — all five are standalone,
hand-invoked engineer utilities. That means migrating them carries no risk of
breaking an existing call site; it is purely a template-completeness gap (an agent
told to survey `templates/sim_scripts/` for build-infrastructure precedent
currently finds 4 of 9 real USB debug/codegen utilities missing, which is exactly
the discoverability gap CLAUDE.md's consolidation-status note already flags).
