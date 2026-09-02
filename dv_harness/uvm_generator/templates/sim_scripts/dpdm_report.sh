#!/bin/sh
#=============================================================================
# dpdm_report.sh -- headless Verdi/FSDB export of both ports' physical-layer
# differential signal pair(s) over a time window.
#
# Usage: sh dpdm_report.sh <fsdb-file> [begin-time-ns] [end-time-ns]
#
# GENERIC TEMPLATE NOTE: narrower than the other two fsdbreport wrappers in
# this directory (apb_timing_report.sh, irq_report.sh). Only the SHAPE is
# generic -- fsdbreport-per-signal export via the shared
# fsdb_signal_report.sh engine, matching waves.tcl's group 5/5b "is there
# anything at all on the wire" question (IP_UVM_DV_Gen.md Step 9). The
# SUBJECT is not generic: dp/dm (USB 2.0 data-plus/data-minus) are a
# USB-protocol electrical concept with no direct equivalent in every
# protocol this Harness covers -- PCIe has its own TX/RX differential
# pairs, MIPI CSI-2/DSI has clock/data lanes, and a pure register-bus target
# (e.g. an AMBA-fabric-as-DUT environment) may have no serial PHY at all.
#
# TARGET_IP's own physical-layer signal pair name(s) -- if this protocol's
# PHY even has an analogous pair -- must be substituted into SIGNALS below
# before reuse. A protocol with no such concept should drop this file
# entirely rather than force-fit it (matches the Makefile's own guidance for
# a protocol-specific knob with no equivalent axis on another protocol).
#
# TB/DUT/SSVOUT/IPTOP_IDX0/IPTOP_IDX1 reuse waves.tcl's exact variable
# names/values. u_udc_usb31_top is this template's original USB project's
# real per-port controller sub-block instance name (same as waves.tcl's
# own IP0/IP1) -- re-derive the equivalent for the current DUT.
#=============================================================================
TARGET_IP="${TARGET_IP:-USB}"
IP_PREFIX="${IP_PREFIX:-usb_}"

TB="sysn063"
DUT="$TB.u_lan063"
SSVOUT="$DUT.u_ss_vout"
IPTOP_IDX0="[0]"
IPTOP_IDX1="[1]"
IP0="$SSVOUT.u_${IP_PREFIX}top$IPTOP_IDX0.u_udc_usb31_top"
IP1="$SSVOUT.u_${IP_PREFIX}top$IPTOP_IDX1.u_udc_usb31_top"

SIGNALS="${SIGNALS:-p0_dp=${IP0}.dp p0_dm=${IP0}.dm p1_dp=${IP1}.dp p1_dm=${IP1}.dm}"

ET=1000000
. "$(cd "$(dirname "$0")" && pwd)/fsdb_signal_report.sh"
