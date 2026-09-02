#!/bin/sh
#=============================================================================
# analyze_sim.sh -- quick summary of one run's sim.log: latest simulated
# timestamp, LSF job status (if still running), UVM_ERROR count, a
# FINAL_CHECK/SvtTestEpilog marker count, and a breakdown of error
# signatures.
#
# GENERIC TEMPLATE NOTE: this file is protocol-agnostic log-triage
# mechanics, generalized from a real USB proving-ground project. 21 of the
# original 24 lines apply to any protocol's sim.log unmodified: the latest-
# timestamp tail, `bjobs` status, the UVM_ERROR count (a UVM concept, not a
# USB one), the FINAL_CHECK/SvtTestEpilog marker count (a UVM/SVT VIP
# convention used across every protocol VIP in this family), and the
# error-signature histogram keyed on the `[category:subcategory]` bracket
# convention this harness's own scoreboards already use generically.
#
# Exactly one line is protocol content: the DMA-scoreboard hit count below,
# parameterized through IP_PREFIX (same vocabulary as the Makefile). It
# grep's for a literal component NAME, and this template's original USB
# project's real scoreboard component was named usb_dma_sb -- confirm the
# CURRENT project's own scoreboard component name against its own
# environment (env/*_scoreboard.sv) rather than assuming it matches
# ${IP_PREFIX}dma_sb literally; drop the line (or point it at a different
# component) if this protocol has no equivalent scoreboard.
#
# Usage: sh analyze_sim.sh <path-to-sim.log> [lsf-job-id]
#=============================================================================
IP_PREFIX="${IP_PREFIX:-usb_}"

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
grep -ac "${IP_PREFIX}dma_sb" "$LOG"
echo FINALCHECK:
grep -acE "SvtTestEpilog:|FINAL_CHECK\(" "$LOG"
echo ---ERRSIGNATURES---
grep -a UVM_ERROR "$LOG" | sed -E "s/^UVM_ERROR //" | grep -oE "\[[a-zA-Z_0-9]+:[a-zA-Z_0-9]+\]|\[register_fail:[^]]+\]" | sort | uniq -c | sort -rn
