#!/bin/sh
# =============================================================================
# lsf_run.sh -- run one command locally, as an LSF batch job, or interactively
#
#   sh lsf_run.sh <mode> <queue> <jobname> <timeout_min> <logfile> -- cmd [args...]
#
# Every VCS invocation in the Makefile goes through this, so where a tool runs
# is one variable rather than a different arrangement per target.
#
# THE THREE MODES
# ---------------
#   off     exec the command. No LSF involved, and no extra process either.
#   batch   bsub -K. Blocks until the job ends AND returns the job's exit
#           status, which is what make needs -- a non-blocking bsub would
#           report success the moment the job was accepted, and the next
#           stage would start against a simv that does not exist yet.
#   int     bsub -Is. A pseudo-terminal is allocated and stdin/stdout stay
#           connected, which is what a GUI or an interactive simv needs.
#   detach  plain bsub. Returns a job ID immediately and the job outlives the
#           submitting shell.
#
# WHY detach EXISTS, AND WHEN batch IS THE WRONG CHOICE
# -----------------------------------------------------
# -K ties the job's lifetime to the shell that submitted it. That is exactly
# what a person at a terminal wants -- the verdict comes back, and `make`
# fails when the job fails. It is fatal when the submitting shell is a telnet
# session with a per-command timeout, which is how this project reaches the
# farm: job 93426 was killed at 00:03:04 with TERM_OWNER after eight minutes
# at a healthy 20.7% CPU, because hop.py's 1800 s limit expired and took the
# shell with it.
#
# CLAUDE.md trap 94 recorded this signature and attributed it to a blanket
# bkill loop in a helper script. That loop was real and did kill four runs,
# but the note also observed that "a later run with a script containing no
# kill at all died the same way, so something else is also involved". This is
# that something else.
#
# detach gives up the exit status -- there is nothing to wait for -- so the
# caller must follow the job with bjobs and read the log. Do not use it for a
# build stage that a later stage depends on: make would carry on against a
# simv that does not exist yet, which is the reason batch uses -K.
#
# The names come from the site's own vocabulary: runr.pl distinguishes
# LSF_INT from LSF_ON the same way. What does NOT carry over is its `-lsfint`
# flag -- that belongs to Calibre and CustomSim, which have LSF support built
# in (see /eda/sunplus/scripts/rc_stage1, where -lsfint is passed to calibre).
# VCS and Verdi have no such option, so for them the interactive mode has to
# be bsub -Is.
#
# WHY -W IS ALWAYS PASSED
# -----------------------
# `bqueues -l vcs` declares no RUNLIMIT. Nothing else bounds a job, so a
# wedged elaboration would hold a host and a licence until a person noticed.
# The caller always supplies a timeout.
#
# CWD. LSF starts the job in the submitting directory, which is what the
# Makefile's `cd $(SIMDIR) && ...` has already set. Nothing here changes it:
# vcs.opt's relative paths depend on it.
# =============================================================================
set -u

MODE=${1:-off}; shift
QUEUE=${1:-vcs}; shift
JOBNAME=${1:-job}; shift
TIMEOUT=${1:-60}; shift
LOGFILE=${1:-/dev/null}; shift
[ "${1:-}" = "--" ] && shift

if [ $# -eq 0 ]; then
  echo "lsf_run: no command given" >&2
  exit 2
fi

case "$MODE" in
  off|0|"")
    exec "$@"
    ;;

  batch|1|on)
    mkdir -p "$(dirname "$LOGFILE")" 2>/dev/null
    echo "[lsf] batch  queue=$QUEUE  job=$JOBNAME  limit=${TIMEOUT}min"
    echo "[lsf]   $*"
    # -K returns the job's own exit status, so `make` fails when the job fails.
    bsub -K -q "$QUEUE" -J "$JOBNAME" -W "$TIMEOUT" -o "$LOGFILE" "$@"
    rc=$?
    if [ $rc -ne 0 ]; then
      echo "[lsf] job $JOBNAME exited $rc. LSF output:" >&2
      [ -f "$LOGFILE" ] && tail -30 "$LOGFILE" >&2
    fi
    exit $rc
    ;;

  detach|detached|bg)
    mkdir -p "$(dirname "$LOGFILE")" 2>/dev/null
    echo "[lsf] detach  queue=$QUEUE  job=$JOBNAME  limit=${TIMEOUT}min"
    echo "[lsf]   $*"
    # No -K and no -Is. bsub prints "Job <nnnnn> is submitted..." and returns,
    # so this shell can go away without taking the job with it.
    bsub -q "$QUEUE" -J "$JOBNAME" -W "$TIMEOUT" -o "$LOGFILE" "$@"
    rc=$?
    if [ $rc -ne 0 ]; then
      echo "[lsf] SUBMISSION failed with $rc -- the job never started." >&2
      exit $rc
    fi
    # Deliberately 0: the submission succeeded. The job's own outcome is not
    # knowable here and must be read with bjobs and $LOGFILE.
    echo "[lsf] submitted detached. Follow it with: bjobs -J $JOBNAME"
    exit 0
    ;;
  int|interactive|2)
    echo "[lsf] interactive  queue=$QUEUE  job=$JOBNAME  limit=${TIMEOUT}min"
    echo "[lsf]   $*"
    # No -o: the point of interactive is that output comes back to this
    # terminal. -Is allocates the pseudo-terminal a GUI or a prompt needs.
    bsub -Is -q "$QUEUE" -J "$JOBNAME" -W "$TIMEOUT" "$@"
    exit $?
    ;;

  *)
    echo "lsf_run: unknown mode '$MODE' (use off, batch, detach or int)" >&2
    exit 2
    ;;
esac
