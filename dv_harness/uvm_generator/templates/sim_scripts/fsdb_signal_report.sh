#!/bin/sh
#=============================================================================
# fsdb_signal_report.sh -- shared engine for a headless FSDB signal-group
# export: given an FSDB and a time window, run VERDI_HOME's fsdbreport once
# per signal of interest, write each to its own /tmp text file, and report
# line counts. This is the batch/headless equivalent of what waves.tcl's
# addGroup does for the interactive Verdi case (same "one useful question,
# one named group of signals" shape, IP_UVM_DV_Gen.md Step 9) -- it exists
# so a different signal group is a DATA change here, not a structural edit.
#
# GENERIC TEMPLATE NOTE: this file is the reusable SHAPE only -- positional
# arg parsing, the fsdbreport-per-signal loop, and the wc -l summary. It
# deliberately carries NO signal list of its own: WHICH signals answer which
# question is protocol/question content, supplied entirely by a per-question
# WRAPPER script in this same directory (apb_timing_report.sh, dpdm_report.sh,
# irq_report.sh) via the SIGNALS environment variable. Do not hardcode a
# default SIGNALS list into this file -- the whole point of centralizing the
# loop here, instead of leaving apb_timing_report.sh/dpdm_report.sh/
# irq_report.sh as three independent copy-pasted scripts (which is how this
# template's original USB project shipped them), is to remove the drift risk
# of the same loop existing three times and being fixed in only one place.
#
# NOT MEANT TO BE RUN DIRECTLY. A wrapper sets ET's default and SIGNALS, then
# dot-SOURCES this file (not exec's it), e.g.:
#
#     ET=1000000
#     . "$(cd "$(dirname "$0")" && pwd)/fsdb_signal_report.sh"
#
# Sourcing (POSIX `.`), not `sh fsdb_signal_report.sh ...`, matters here: it
# runs this file's F/BT/ET/report loop inside the WRAPPER's own shell, so the
# wrapper's own positional parameters ($1 fsdb file, $2 begin-time,
# $3 end-time) are still the ones read below, and the wrapper's SIGNALS/ET
# variables are already in scope without having to re-pass them.
#
# SIGNALS FORMAT: whitespace-separated "label=hierarchical.path" tokens, e.g.
#     SIGNALS="psel=\$SSVOUT.u_\${IP_PREFIX}top\$IPTOP_IDX1.usb_s_psel pready=..."
# One token per fsdbreport call; label becomes /tmp/<label>.txt (+.log for
# the fsdbreport tool's own transcript). '=' is the label/path delimiter, not
# ':' -- a bit-select path segment like "interrupt[19:0]" already contains a
# colon, and splitting on the first ':' there would cut the path in half.
# Tokens are whitespace-separated (not newline-delimited, not read through a
# piped `while read`) on purpose: a `... | while read` here would run the
# loop in a SUBSHELL and lose OUTFILES the moment the pipeline exits, the
# same class of pitfall CLAUDE.md's evidence-discipline notes call out
# elsewhere for anything that quietly runs in a subshell.
#=============================================================================
V=$VERDI_HOME/bin/fsdbreport
F=${1:?usage: sh <wrapper>.sh <fsdb-file> [begin-time-ns] [end-time-ns]}
BT=${2:-0}
ET=${3:-$ET}
: "${SIGNALS:?fsdb_signal_report.sh: SIGNALS is unset -- source this file from a wrapper (apb_timing_report.sh / dpdm_report.sh / irq_report.sh) that defines it; do not run it directly}"

OUTFILES=""
for pair in $SIGNALS; do
  label=${pair%%=*}
  path=${pair#*=}
  out="/tmp/${label}.txt"
  $V $F -bt $BT -et $ET -verilog -s "$path" -o "$out" > "/tmp/${label}.log" 2>&1
  OUTFILES="$OUTFILES $out"
done

echo DONE
wc -l $OUTFILES
