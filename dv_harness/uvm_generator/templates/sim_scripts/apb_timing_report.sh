#!/bin/sh
#=============================================================================
# apb_timing_report.sh -- headless Verdi/FSDB export of one register-bus
# slave-select handshake (psel/pready/penable) over a time window.
#
# Usage: sh apb_timing_report.sh <fsdb-file> [begin-time-ns] [end-time-ns]
#
# GENERIC TEMPLATE NOTE: the SHAPE is generic and is exactly waves.tcl's
# group "3b APB slave decode" re-expressed as a batch/headless fsdbreport
# export instead of an interactive wvAddSignal call -- take an FSDB path
# plus an optional [begin,end] window, export one signal per fsdbreport
# call (via fsdb_signal_report.sh, shared with dpdm_report.sh/
# irq_report.sh), report line counts. This script and waves.tcl's group 3b
# answer the SAME question in two different tools (headless script vs.
# interactive GUI) and should be kept in sync if one is updated.
#
# What is NOT generic is the hierarchical path and register-bus signal
# names below (usb_s_psel/pready/penable under u_${IP_PREFIX}top[1]) -- real
# RTL facts about this template's original USB SoC, identical in kind to
# waves.tcl's own TB/DUT/SSVOUT path variables, which are reused here by
# name so the two files agree. Re-derive the current DUT's own register-bus
# slave-select signal names from its RTL before reusing this on another
# protocol/project; do not assume they match usb_s_* literally.
#=============================================================================
TARGET_IP="${TARGET_IP:-USB}"
IP_PREFIX="${IP_PREFIX:-usb_}"

# Paths -- same names and values as waves.tcl. Change TB and DUT here, not
# in the signal list below, if the current DUT's testbench-top hierarchy
# differs (see waves.tcl's own comment on sysn063/u_lan063/u_ss_vout).
TB="sysn063"
DUT="$TB.u_lan063"
SSVOUT="$DUT.u_ss_vout"
# u_<ip>top is an array unless HAPS is defined (waves.tcl's own note);
# port 1 only, matching this template's original single-port worked example.
IPTOP_IDX1="[1]"

SIGNALS="${SIGNALS:-p1_psel=${SSVOUT}.u_${IP_PREFIX}top${IPTOP_IDX1}.usb_s_psel p1_pready=${SSVOUT}.u_${IP_PREFIX}top${IPTOP_IDX1}.usb_s_pready p1_penable=${SSVOUT}.u_${IP_PREFIX}top${IPTOP_IDX1}.usb_s_penable}"

ET=1000000
. "$(cd "$(dirname "$0")" && pwd)/fsdb_signal_report.sh"
