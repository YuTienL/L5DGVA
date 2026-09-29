#!/bin/sh
#=============================================================================
# irq_report.sh -- headless Verdi/FSDB export of both ports' interrupt/
# event-status lines over a time window.
#
# Usage: sh irq_report.sh <fsdb-file> [begin-time-ns] [end-time-ns]
#
# GENERIC TEMPLATE NOTE: structurally generic -- interrupt/event-status
# lines are a cross-protocol concept (every protocol in this Harness's scope
# has some interrupt/error-status signal), and waves.tcl's own group 8
# already treats this generically: "nothing in the environment currently
# checks these, so watching them here is the only way they are seen at
# all." The SHAPE (fsdbreport-per-signal export via the shared
# fsdb_signal_report.sh engine) is the same as apb_timing_report.sh and
# dpdm_report.sh.
#
# TB/DUT/SSVOUT/IPTOP_IDX0/IPTOP_IDX1/IP0/IP1 reuse waves.tcl's exact
# variable names/values. usbirq, u_usbwrapper_usb and interrupt[19:0] below
# are this template's original USB project's real interrupt-line and
# wrapper sub-block names -- re-derive the current DUT's own equivalents
# from its RTL before reuse.
#
# ET's default is 2,000,000 ns -- double apb_timing_report.sh's/
# dpdm_report.sh's 1,000,000 -- a TUNING constant carried over from this
# template's original project, not a structural one: interrupt-worthy
# events happened later in that project's own patterns than register
# writes did. Re-tune for TARGET_IP's own pattern timing rather than
# assuming this window is long enough.
#=============================================================================
TARGET_IP="${TARGET_IP:-USB}"
IP_PREFIX="${IP_PREFIX:-usb_}"
IP_PREFIX_STEM="${IP_PREFIX%_}"

TB="sysn063"
DUT="$TB.u_lan063"
SSVOUT="$DUT.u_ss_vout"
IPTOP_IDX0="[0]"
IPTOP_IDX1="[1]"
IP0="$SSVOUT.u_${IP_PREFIX}top$IPTOP_IDX0.u_udc_usb31_top"
IP1="$SSVOUT.u_${IP_PREFIX}top$IPTOP_IDX1.u_udc_usb31_top"

SIGNALS="${SIGNALS:-p0_irq=${SSVOUT}.u_${IP_PREFIX}top${IPTOP_IDX0}.u_${IP_PREFIX_STEM}wrapper_${IP_PREFIX_STEM}.usbirq p1_irq=${SSVOUT}.u_${IP_PREFIX}top${IPTOP_IDX1}.u_${IP_PREFIX_STEM}wrapper_${IP_PREFIX_STEM}.usbirq p0_intr=${IP0}.interrupt[19:0] p1_intr=${IP1}.interrupt[19:0]}"

ET=2000000
. "$(cd "$(dirname "$0")" && pwd)/fsdb_signal_report.sh"
